import asyncio
import shutil
import tempfile
import time
from pathlib import Path

from scp.daemon import gameplay, procurement
from scp.daemon.content.items import ItemProfile
from scp.daemon.hardware import catalog as hw
from scp.daemon.main import Daemon


async def test():
    td = Path(tempfile.mkdtemp())
    try:
        d = Daemon(db_path=td / "p6.db", port=54100)
        gameplay.bootstrap_if_empty(d.journal)
        d.scheduler.rehydrate()
        await d.ipc.start()
        st = asyncio.create_task(d.scheduler.run())
        d.journal.set_funding(5_000_000)

        print("=== 1) new SKU categories present ===")
        sa = [s for s in hw.SKUS.values() if s.category == "storage_array"]
        tl = [s for s in hw.SKUS.values() if s.category == "tape_library"]
        hm = [s for s in hw.SKUS.values() if s.category == "host_module"]
        print(f"  storage_array: {len(sa)}  tape_library: {len(tl)}  host_module: {len(hm)}")
        assert len(sa) >= 3 and len(tl) >= 3 and len(hm) >= 4

        print()
        print("=== 2) item generator assigns size_gb ===")
        from scp.daemon.content.items import generate
        import random as _r
        seen = {c: [] for c in ("Safe", "Euclid", "Keter")}
        for i in range(50):
            p = generate(_r.Random(i))
            seen[p.item_class].append(p.size_gb)
        for c, sizes in seen.items():
            if sizes:
                print(f"  {c:7s}: n={len(sizes)}  min={min(sizes):.1f}  max={max(sizes):.1f} GB")

        print()
        print("=== 3) bootstrap starter storage + tape library ===")
        util = procurement.site_utilization(d.journal, 1)
        print(f"  site 1: storage_cap={util['storage_cap_gb']:.0f} GB "
              f"tape_cap={util['tape_cap_gb']:.0f} GB RAM={util['ram_cap_gb']} GB")
        assert util["storage_cap_gb"] >= 2_000      # 2 TB from host
        assert util["tape_cap_gb"] >= 500_000       # 500 TB library

        print()
        print("=== 4) storage array install raises capacity ===")
        r = procurement.buy(d.journal, d.scheduler.add, "storage-array-48tb-ssd")
        procurement.on_install_complete(d.journal, r["purchase_id"])
        util2 = procurement.site_utilization(d.journal, 1)
        print(f"  after 48TB SSD array: storage_cap={util2['storage_cap_gb']:.0f} GB")
        assert util2["storage_cap_gb"] == util["storage_cap_gb"] + 48_000

        print()
        print("=== 5) tape library install raises tape cap ===")
        r = procurement.buy(d.journal, d.scheduler.add, "tape-lib-med")
        procurement.on_install_complete(d.journal, r["purchase_id"])
        util3 = procurement.site_utilization(d.journal, 1)
        print(f"  after 5PB library: tape_cap={util3['tape_cap_gb']:.0f} GB")
        assert util3["tape_cap_gb"] == util2["tape_cap_gb"] + 5_000_000

        print()
        print("=== 6) host_module (RAM/storage) upgrades a host ===")
        host = d.journal.get_host(1)
        ram_before = int(host["specs"].get("ram_gb", 0))
        storage_before = int(host["specs"].get("storage_gb", 0))
        print(f"  host-01 before: ram={ram_before}GB storage={storage_before}GB")
        r = procurement.buy(d.journal, d.scheduler.add, "host-ram-512gb")
        ir = procurement.on_install_complete(d.journal, r["purchase_id"])
        print(f"  RAM upgrade: {ir.get('before')} -> {ir.get('after')}")
        r = procurement.buy(d.journal, d.scheduler.add, "host-storage-hdd-48tb")
        ir = procurement.on_install_complete(d.journal, r["purchase_id"])
        print(f"  storage upgrade: {ir.get('before')} -> {ir.get('after')}")
        host2 = d.journal.get_host(1)
        assert int(host2["specs"]["ram_gb"]) == ram_before + 512
        assert int(host2["specs"]["storage_gb"]) == storage_before + 48_000

        print()
        print("=== 7) acquire accounts for size + auto-encrypts ===")
        p = ItemProfile("SCP-7001", "Safe", 3, 1, 0, 0, "t", "t", size_gb=10)
        iid = d.journal.create_item(
            p.designation, p.item_class, p.hazard_strength, p.to_dict()
        )
        d.journal.set_item_size(iid, 10)
        storage_before = procurement.site_utilization(d.journal, 1)["storage_used_gb"]
        gameplay.acquire_candidate(d.journal, iid)
        item = d.journal.get_item(iid)
        storage_after = procurement.site_utilization(d.journal, 1)["storage_used_gb"]
        print(f"  size_gb={item['size_gb']}  encrypted_at_rest={item['encrypted_at_rest']}  "
              f"storage_used {storage_before:.0f} -> {storage_after:.0f} GB")
        assert item["encrypted_at_rest"] is True  # bootstrap has software enc
        assert storage_after == storage_before + 10

        print()
        print("=== 8) acquire without encryption flags unencrypted_at_rest ===")
        d.journal.set_site_encryption(1, "none")
        p2 = ItemProfile("SCP-7002", "Safe", 2, 0, 0, 0, "t", "t", size_gb=5)
        iid2 = d.journal.create_item(
            p2.designation, p2.item_class, p2.hazard_strength, p2.to_dict()
        )
        d.journal.set_item_size(iid2, 5)
        gameplay.acquire_candidate(d.journal, iid2)
        item2 = d.journal.get_item(iid2)
        print(f"  encrypted_at_rest={item2['encrypted_at_rest']}")
        assert item2["encrypted_at_rest"] is False
        recent = [e for e in d.journal.recent(20) if e["kind"] == "unencrypted_at_rest"]
        print(f"  unencrypted_at_rest events: {len(recent)}")
        assert len(recent) >= 1

        print()
        print("=== 9) acquire refused when storage full ===")
        # Fill up with a huge item
        huge = ItemProfile("SCP-7003", "Keter", 20, 8, 8, 8, "t", "t",
                           size_gb=50_000_000)
        iid3 = d.journal.create_item(huge.designation, huge.item_class,
                                     huge.hazard_strength, huge.to_dict())
        d.journal.set_item_size(iid3, 50_000_000)
        try:
            gameplay.acquire_candidate(d.journal, iid3)
            assert False, "should have refused"
        except ValueError as e:
            print(f"  PASS: {e}")

        st.cancel()
        try:
            await st
        except (asyncio.CancelledError, Exception):
            pass
        d.journal.close()
        print()
        print("---PHASE 6 TESTS PASSED---")
    finally:
        time.sleep(0.2)
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test())
