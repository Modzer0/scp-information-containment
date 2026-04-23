"""
Phase 16 — VMs inherit host base containment + deprovision.

Covers:
- mainframe procurement stashes auto_vm_spec on host specs
- additional VMs on a mainframe inherit containment=30 (not seed=6)
- server hosts: new VMs still get the generic seed spec
- deprovision_vm removes a VM and redistributes RAM
- deprovision refuses when VM is busy
- deprovision clears item.current_vm_id pointers
- name-pattern fallback lets older saves (no auto_vm_spec in specs) still
  inherit via catalog lookup
"""
import asyncio
import shutil
import tempfile
import time
from pathlib import Path

from scp.daemon import gameplay, procurement
from scp.daemon.content.items import ItemProfile
from scp.daemon.main import Daemon


async def test():
    td = Path(tempfile.mkdtemp())
    try:
        d = Daemon(db_path=td / "p16.db", port=54916)
        gameplay.bootstrap_if_empty(d.journal)
        d.scheduler.rehydrate()
        await d.ipc.start()
        st = asyncio.create_task(d.scheduler.run())
        d.journal.set_funding(200_000_000)

        print("=== 1) server host: new VM falls back to seed spec ===")
        r_s = gameplay.provision_vm(d.journal, host_id=1)
        # Bootstrap 64 GB server has no auto_vm_spec → seed (containment ~6)
        assert r_s["base_containment"] == 6, f"got {r_s['base_containment']}"
        print(f"  server provision_vm → containment={r_s['base_containment']}  OK")

        print()
        print("=== 2) mainframe auto_vm_spec stored on host specs at install ===")
        rb = procurement.buy(d.journal, d.scheduler.add,
                             sku_id="ibex-z-base", target_site_id=1)
        await d._flush_pending()
        mf = next(h for h in d.journal.list_hosts() if h["class"] == "mainframe")
        assert "auto_vm_spec" in mf["specs"]
        avs = mf["specs"]["auto_vm_spec"]
        assert sum(int(v) for v in avs.values()) == 30
        print(f"  mainframe host {mf['id']} specs.auto_vm_spec present, sums to 30  OK")

        print()
        print("=== 3) first LPAR already has containment 30 ===")
        mf_vms = [v for v in d.journal.list_vms() if v["host_id"] == mf["id"]]
        assert len(mf_vms) == 1
        first_cont = sum(int(v) for v in mf_vms[0]["spec"].values())
        assert first_cont == 30
        print(f"  first LPAR containment = {first_cont}  OK")

        print()
        print("=== 4) additional LPAR inherits containment 30 ===")
        r2 = gameplay.provision_vm(d.journal, host_id=mf["id"])
        assert r2["base_containment"] == 30, f"got {r2['base_containment']}"
        v2 = d.journal.get_vm(r2["vm_id"])
        assert sum(int(v) for v in v2["spec"].values()) == 30
        print(f"  second LPAR containment = 30  OK")

        print()
        print("=== 5) deprovision redistributes RAM ===")
        r3 = gameplay.provision_vm(d.journal, host_id=mf["id"])
        assert d.journal.count_vms_on_host(mf["id"]) == 3
        depr = gameplay.deprovision_vm(d.journal, r3["vm_id"])
        assert depr["remaining_vms_on_host"] == 2
        # Mainframe = 2048 GB; 2 VMs → 1024 each
        assert depr["allocated_ram_gb_each"] == 1024
        assert d.journal.get_vm(r3["vm_id"]) is None  # gone from DB
        print(f"  deprovisioned → 2 LPARs × 1024 GB  OK")

        print()
        print("=== 6) deprovision refuses on a busy VM ===")
        d.journal._conn.execute(
            "UPDATE vms SET status = 'busy' WHERE id = ?", (mf_vms[0]["id"],)
        )
        try:
            gameplay.deprovision_vm(d.journal, mf_vms[0]["id"])
            assert False, "should reject busy VM"
        except ValueError as e:
            print(f"  busy VM rejected: {e}")
        d.journal._conn.execute(
            "UPDATE vms SET status = 'idle' WHERE id = ?", (mf_vms[0]["id"],)
        )

        print()
        print("=== 7) deprovision clears item.current_vm_id ===")
        p = ItemProfile("SCP-DPR", "Safe", 2, 0, 0, 0, "t", "t", size_gb=1)
        iid = d.journal.create_item(p.designation, p.item_class, p.hazard_strength, p.to_dict())
        d.journal.set_item_state(iid, "quarantined", current_vm_id=mf_vms[0]["id"])
        before = d.journal.get_item(iid)
        assert before["current_vm_id"] == mf_vms[0]["id"]
        gameplay.deprovision_vm(d.journal, mf_vms[0]["id"])
        after = d.journal.get_item(iid)
        assert after["current_vm_id"] is None
        print(f"  item vm pointer cleared after deprovision  OK")

        print()
        print("=== 8) name-pattern fallback for hosts without auto_vm_spec in specs ===")
        # Simulate an older save: strip auto_vm_spec from a newly-created mainframe
        # and verify provision_vm still inherits via catalog name lookup.
        rb2 = procurement.buy(d.journal, d.scheduler.add,
                              sku_id="ibex-z-base", target_site_id=1)
        await d._flush_pending()
        mf2 = [h for h in d.journal.list_hosts() if h["class"] == "mainframe"][-1]
        specs = dict(mf2["specs"])
        specs.pop("auto_vm_spec", None)
        d.journal.update_host_specs(mf2["id"], specs)
        # Confirm removal
        assert "auto_vm_spec" not in d.journal.get_host(mf2["id"])["specs"]
        # Now provision — should still inherit from catalog
        r_back = gameplay.provision_vm(d.journal, host_id=mf2["id"])
        assert r_back["base_containment"] == 30, f"got {r_back['base_containment']}"
        print(f"  legacy-host fallback → containment 30  OK")

        st.cancel()
        try:
            await st
        except (asyncio.CancelledError, Exception):
            pass
        d.journal.close()
        print()
        print("---PHASE 16 TESTS PASSED---")
    finally:
        time.sleep(0.2)
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test())
