"""
Phase 18 — compound compute modules + host-wide containment upgrades.

Covers:
- compute_module (panthalassa-core) unpacks to N hosts + M cooling units
- each bundled host gets its own VM with the bundle's auto_vm_spec
- container-compute-20ft-hs ships with hardened baseline containment=21
- host_containment_module applies to host specs + every VM on the host
- newly provisioned VMs inherit the upgraded host baseline
- site_cooling_kw_bonus increases site cooling capacity
- host-wide SKUs take MAX(existing, new value) so upgrades don't downgrade
"""
import asyncio
import shutil
import tempfile
import time
from pathlib import Path

from scp.daemon import gameplay, procurement
from scp.daemon.main import Daemon


async def test():
    td = Path(tempfile.mkdtemp())
    try:
        d = Daemon(db_path=td / "p18.db", port=54918)
        gameplay.bootstrap_if_empty(d.journal)
        d.scheduler.rehydrate()
        await d.ipc.start()
        st = asyncio.create_task(d.scheduler.run())
        d.journal.set_funding(100_000_000_000)

        print("=== 1) panthalassa-core unpacks to 4 hosts + 2 cooling units ===")
        hosts_before = len(d.journal.list_hosts())
        cooling_before = len(d.journal.list_cooling_units())
        procurement.buy(d.journal, d.scheduler.add,
                        sku_id="panthalassa-core", target_site_id=1)
        await d._flush_pending()
        assert len(d.journal.list_hosts()) - hosts_before == 4
        assert len(d.journal.list_cooling_units()) - cooling_before == 2
        panth_hosts = [
            h for h in d.journal.list_hosts() if "panth-node" in h["name"]
        ]
        assert len(panth_hosts) == 4

        # Each host has one VM, with the bundle's auto_vm_spec (cont=10)
        for h in panth_hosts:
            vms = [v for v in d.journal.list_vms() if v["host_id"] == h["id"]]
            assert len(vms) == 1
            cont = sum(int(x) for x in vms[0]["spec"].values())
            assert cont == 10, f"host {h['id']} cont={cont}"
            assert "auto_vm_spec" in h["specs"]
        print(f"  4 nodes + 2 cooling, each VM containment=10  OK")

        print()
        print("=== 2) container-compute-20ft-hs: hardened baseline 21 ===")
        procurement.buy(d.journal, d.scheduler.add,
                        sku_id="container-compute-20ft-hs", target_site_id=1)
        await d._flush_pending()
        hs_hosts = [h for h in d.journal.list_hosts() if "hs-node" in h["name"]]
        assert len(hs_hosts) == 4
        for h in hs_hosts:
            vms = [v for v in d.journal.list_vms() if v["host_id"] == h["id"]]
            cont = sum(int(x) for x in vms[0]["spec"].values())
            assert cont == 21, f"hs host {h['id']} cont={cont}"
        print(f"  4 HS nodes, each VM containment=21  OK")

        print()
        print("=== 3) site_cooling_kw_bonus increases site cooling cap ===")
        util = procurement.site_utilization(d.journal, 1)
        # site-17 bootstrap ships with 20 kW cooling; panthalassa-core +120 kW,
        # container-hs +80 kW → expect at least 220 kW
        print(f"  site 1 cooling cap = {util['cooling_kw_capacity']} kW")
        assert util["cooling_kw_capacity"] >= 220

        print()
        print("=== 4) host-scsc-vault: bumps host + every VM's shield to 6 ===")
        target = panth_hosts[0]
        # Provision an additional VM to prove cascade works on siblings
        gameplay.provision_vm(d.journal, host_id=target["id"])
        vms_on = [v for v in d.journal.list_vms() if v["host_id"] == target["id"]]
        # Before: shields=4 (panth baseline)
        assert all(int(v["spec"].get("physical_shielding", 0)) == 4 for v in vms_on)

        procurement.buy(d.journal, d.scheduler.add,
                        sku_id="host-scsc-vault", target_vm_id=target["id"])
        await d._flush_pending()

        vms_on = [v for v in d.journal.list_vms() if v["host_id"] == target["id"]]
        assert all(int(v["spec"]["physical_shielding"]) == 6 for v in vms_on)
        # Host baseline updated
        h_after = d.journal.get_host(target["id"])
        assert h_after["specs"]["auto_vm_spec"]["physical_shielding"] == 6
        print(f"  host {target['id']} + {len(vms_on)} VMs all at shield=6  OK")

        print()
        print("=== 5) newly provisioned VM inherits upgraded baseline ===")
        r_new = gameplay.provision_vm(d.journal, host_id=target["id"])
        new_vm = d.journal.get_vm(r_new["vm_id"])
        assert int(new_vm["spec"]["physical_shielding"]) == 6
        new_cont = sum(int(x) for x in new_vm["spec"].values())
        # Baseline was 10 (panth), shield now +2 to 6 → new cont = 12
        assert new_cont == 12, f"got {new_cont}"
        print(f"  new VM inherits shield=6, containment={new_cont}  OK")

        print()
        print("=== 6) host upgrade takes MAX (no downgrade) ===")
        # host-polarized-shielding has value=4, shield is already 6 — should stay 6
        procurement.buy(d.journal, d.scheduler.add,
                        sku_id="host-polarized-shielding", target_vm_id=target["id"])
        await d._flush_pending()
        vms_on = [v for v in d.journal.list_vms() if v["host_id"] == target["id"]]
        assert all(int(v["spec"]["physical_shielding"]) == 6 for v in vms_on)
        print(f"  polarized (value=4) after scsc (value=6): stays at 6  OK")

        print()
        print("=== 7) different components stack — mnestic AND memenc ===")
        procurement.buy(d.journal, d.scheduler.add,
                        sku_id="host-mnestic-firmware", target_vm_id=target["id"])
        procurement.buy(d.journal, d.scheduler.add,
                        sku_id="host-hw-memenc", target_vm_id=target["id"])
        await d._flush_pending()
        vms_on = [v for v in d.journal.list_vms() if v["host_id"] == target["id"]]
        for v in vms_on:
            assert int(v["spec"]["mnestic_firmware"]) == 4
            assert int(v["spec"]["memory_encryption"]) == 6
            cont = sum(int(x) for x in v["spec"].values())
            # baseline 10 + shield +2 + mnestic +4 + memenc +3 = 19
            print(f"  vm {v['id']}: cont={cont}  OK")

        st.cancel()
        try:
            await st
        except (asyncio.CancelledError, Exception):
            pass
        d.journal.close()
        print()
        print("---PHASE 18 TESTS PASSED---")
    finally:
        time.sleep(0.2)
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test())
