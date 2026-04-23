"""
Phase 15 — multi-VM provisioning + analyze RAM gate.

Covers:
- provision_vm creates additional VMs on a host
- RAM is divided evenly: host_ram / vm_count
- per-class cap (server=32, aipod=16, mainframe=64)
- per-VM RAM floor (≥ 8 GB) enforced
- cannot provision while siblings are busy
- cannot provision on non-clean host
- analyze blocks when item.size_gb > allocated_ram
- analyze allowed when item fits
- list_vms response includes host_ram_gb + allocated_ram_gb
"""
import asyncio
import shutil
import tempfile
import time
from pathlib import Path

from scp.daemon import gameplay
from scp.daemon.content.items import ItemProfile
from scp.daemon.main import Daemon


async def test():
    td = Path(tempfile.mkdtemp())
    try:
        d = Daemon(db_path=td / "p15.db", port=54915)
        gameplay.bootstrap_if_empty(d.journal)
        d.scheduler.rehydrate()
        await d.ipc.start()
        st = asyncio.create_task(d.scheduler.run())
        d.journal.set_funding(500_000_000)

        # Skilled operator + well-contained default VM so analyze mistakes/guardrails don't
        # reject for unrelated reasons.
        d.journal.update_staff_skills(1, {"infosec": 90, "memetics": 50, "forensics": 20})
        d.journal.update_vm_spec(1, {
            "memory_encryption": 10, "isolation": 8, "mnestic_firmware": 4,
            "physical_shielding": 6, "scanner_freshness": 2,
        })
        d.journal.set_site_encryption(1, "type1")

        print("=== 1) bootstrap: 1 VM on 64 GB host → alloc = 64 GB ===")
        alloc0 = gameplay.vm_allocated_ram_gb(d.journal, 1)
        assert alloc0 == 64, f"got {alloc0}"
        print(f"  vm 1 alloc = {alloc0} GB")

        print()
        print("=== 2) provision more VMs — RAM splits evenly ===")
        r2 = gameplay.provision_vm(d.journal, host_id=1)
        print(f"  add vm → count={r2['vm_count']}  alloc each={r2['allocated_ram_gb']} GB")
        assert r2["vm_count"] == 2
        assert r2["allocated_ram_gb"] == 32
        # vm 1 also sees its allocation shrink
        assert gameplay.vm_allocated_ram_gb(d.journal, 1) == 32

        r3 = gameplay.provision_vm(d.journal, host_id=1)
        assert r3["vm_count"] == 3
        assert r3["allocated_ram_gb"] == 21  # 64 // 3

        r4 = gameplay.provision_vm(d.journal, host_id=1)
        assert r4["vm_count"] == 4
        assert r4["allocated_ram_gb"] == 16
        print(f"  4 VMs on 64 GB host: each allocated 16 GB  OK")

        print()
        print("=== 3) per-VM RAM floor caps VM count ===")
        # 64 GB / 8 = 8 max VMs. Fill to cap then expect reject.
        for _ in range(4):  # already have 4, add 4 more → 8 total
            gameplay.provision_vm(d.journal, host_id=1)
        assert d.journal.count_vms_on_host(1) == 8
        try:
            gameplay.provision_vm(d.journal, host_id=1)
            assert False, "should reject at cap"
        except ValueError as e:
            print(f"  at 8/8: {e}")

        print()
        print("=== 4) analyze blocks when item > allocated RAM ===")
        # Each VM on host 1 now has 64/8 = 8 GB
        # Create a 10 GB Safe item → should NOT fit
        p_big = ItemProfile("SCP-BIG", "Safe", 2, 0, 0, 0, "t", "t", size_gb=10)
        iid_big = d.journal.create_item(
            p_big.designation, p_big.item_class, p_big.hazard_strength, p_big.to_dict()
        )
        gameplay.acquire_candidate(d.journal, iid_big)
        try:
            gameplay.start_analyze(d.journal, d.scheduler.add, iid_big, 1)
            assert False, "10 GB item shouldn't fit in 8 GB VM"
        except ValueError as e:
            print(f"  10 GB item in 8 GB VM rejected: {e}")

        # Create a 5 GB Safe item → fits
        p_small = ItemProfile("SCP-SM", "Safe", 2, 0, 0, 0, "t", "t", size_gb=5)
        iid_small = d.journal.create_item(
            p_small.designation, p_small.item_class, p_small.hazard_strength, p_small.to_dict()
        )
        gameplay.acquire_candidate(d.journal, iid_small)
        r = gameplay.start_analyze(d.journal, d.scheduler.add, iid_small, 1)
        assert not r.get("blocked"), f"5 GB item should fit: {r}"
        print(f"  5 GB item in 8 GB VM: OK")

        print()
        print("=== 5) bigger host + big item: fits ===")
        # Add a large host (1 TB RAM, 1 VM → 1024 GB alloc)
        big_host = d.journal.create_host(
            site_id=1, name="host-big", host_class="server",
            specs={"ram_gb": 1024, "storage_gb": 100_000, "power_w": 2000},
            status="clean",
        )
        big_vm = d.journal.create_vm(
            host_id=big_host, name=f"vm-{big_host}-01",
            spec={"memory_encryption": 10, "isolation": 8, "mnestic_firmware": 4,
                  "physical_shielding": 6, "scanner_freshness": 2},
            status="idle",
        )
        assert gameplay.vm_allocated_ram_gb(d.journal, big_vm) == 1024
        p_k = ItemProfile("SCP-K", "Euclid", 8, 3, 2, 1, "t", "t", size_gb=500)
        iid_k = d.journal.create_item(p_k.designation, p_k.item_class, p_k.hazard_strength, p_k.to_dict())
        gameplay.acquire_candidate(d.journal, iid_k)
        # Need more storage headroom — bump site storage capacity just in case
        r_k = gameplay.start_analyze(d.journal, d.scheduler.add, iid_k, big_vm)
        assert not r_k.get("blocked"), f"500 GB item should fit in 1024 GB VM: {r_k}"
        print(f"  500 GB item in 1024 GB VM: OK")

        print()
        print("=== 6) cannot provision while sibling VM is busy ===")
        # A big_vm analysis is running — try to provision on big_host
        try:
            gameplay.provision_vm(d.journal, host_id=big_host)
            assert False, "should reject while sibling busy"
        except ValueError as e:
            print(f"  busy sibling → reject: {e}")

        print()
        print("=== 7) cannot provision on non-clean host ===")
        d.journal.set_host_status(big_host, "suspect")
        try:
            gameplay.provision_vm(d.journal, host_id=big_host)
            assert False, "should reject suspect host"
        except ValueError as e:
            print(f"  non-clean host → reject: {e}")
        d.journal.set_host_status(big_host, "clean")

        print()
        print("=== 8) per-class cap enforced — mainframe gets 64 ===")
        mf = d.journal.create_host(
            site_id=1, name="host-mf", host_class="mainframe",
            specs={"ram_gb": 8192, "storage_gb": 100_000, "power_w": 20_000},
            status="clean",
        )
        # 8192 / 8 = 1024 → cap should be 64 (LPAR ceiling)
        host = d.journal.get_host(mf)
        cap = gameplay.max_vms_for_host(host)
        assert cap == 64, f"mainframe 8 TB → cap 64, got {cap}"
        print(f"  mainframe 8 TB → cap {cap}  OK")

        aipod = d.journal.create_host(
            site_id=1, name="host-ai", host_class="aipod",
            specs={"ram_gb": 1024, "storage_gb": 100_000, "power_w": 20_000},
            status="clean",
        )
        cap_ai = gameplay.max_vms_for_host(d.journal.get_host(aipod))
        assert cap_ai == 16  # aipod ceiling
        print(f"  aipod 1 TB → cap {cap_ai}  OK")

        print()
        print("=== 9) list_vms reply enriched with allocated_ram_gb ===")
        # via IPC
        import json as _json
        r, w = await asyncio.open_connection("127.0.0.1", 54915, limit=16*1024*1024)
        w.write(b'{"type":"list_vms"}\n')
        await w.drain()
        line = await r.readline()
        w.close()
        try:
            await w.wait_closed()
        except Exception:
            pass
        reply = _json.loads(line)
        vms = reply["payload"]["vms"]
        first = vms[0]
        assert "allocated_ram_gb" in first and "host_ram_gb" in first
        assert "siblings_on_host" in first
        print(f"  vm 1 enriched: alloc={first['allocated_ram_gb']}  "
              f"host_ram={first['host_ram_gb']}  sibs={first['siblings_on_host']}")

        st.cancel()
        try:
            await st
        except (asyncio.CancelledError, Exception):
            pass
        d.journal.close()
        print()
        print("---PHASE 15 TESTS PASSED---")
    finally:
        time.sleep(0.2)
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test())
