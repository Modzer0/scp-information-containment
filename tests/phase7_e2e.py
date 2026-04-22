import asyncio
import shutil
import tempfile
import time
from pathlib import Path

from scp.daemon import gameplay, procurement, sites
from scp.daemon.hardware import catalog as hw
from scp.daemon.main import Daemon


async def test():
    td = Path(tempfile.mkdtemp())
    try:
        d = Daemon(db_path=td / "p7.db", port=54200)
        gameplay.bootstrap_if_empty(d.journal)
        d.scheduler.rehydrate()
        await d.ipc.start()
        st = asyncio.create_task(d.scheduler.run())
        d.journal.set_funding(500_000_000)

        print("=== 1) site types expanded: tent, bunker_shallow, underground+pumps ===")
        types = [t.type_id for t in sites.list_types()]
        print(f"  types: {types}")
        assert "tent" in types
        assert "bunker_shallow" in types
        assert "underground" in types
        underground = sites.get_type("underground")
        print(f"  underground requires_pumps={underground.requires_pumps}")
        assert underground.requires_pumps is True

        print()
        print("=== 2) default storage on server SKUs ===")
        cases = {
            "generic-1u-server": 4_000,
            "generic-2u-server": 24_000,
            "container-compute-20ft": 100_000,
            "invidia-dgz-pod": 100_000,
            "ibex-z-base": 50_000,
        }
        for sku_id, expected in cases.items():
            sku = hw.get(sku_id)
            assert sku is not None, f"missing sku: {sku_id}"
            actual = int(sku.capabilities.get("storage_gb", 0))
            print(f"  {sku_id:25s} storage_gb={actual}")
            assert actual == expected

        print()
        print("=== 3) install 1U server → host has storage ===")
        r = procurement.buy(d.journal, d.scheduler.add, "generic-1u-server")
        ir = procurement.on_install_complete(d.journal, r["purchase_id"])
        host = d.journal.get_host(ir["host_id"])
        print(f"  new host storage_gb={host['specs'].get('storage_gb')}")
        assert int(host["specs"]["storage_gb"]) == 4_000

        print()
        print("=== 4) containerized compute + storage SKUs ===")
        for sku_id in ["container-compute-20ft", "container-storage-20ft"]:
            sku = hw.get(sku_id)
            assert sku is not None
            print(f"  {sku_id:25s} {sku.name}  ${sku.price_usd:,}")

        print()
        print("=== 5) establish underground → pre-installed starter pump ===")
        sites.on_site_established(d.journal, "underground", "Deep-Alpha")
        ug = next(s for s in d.journal.list_sites() if s["name"] == "Deep-Alpha")
        pumps_at_ug = d.journal.count_site_pumps(ug["id"])
        print(f"  pumps at Deep-Alpha: {pumps_at_ug}")
        assert pumps_at_ug == 1
        util = procurement.site_utilization(d.journal, ug["id"])
        print(f"  flooded={util['flooded']} cap={util['power_kw_capacity']}kW")
        assert util["flooded"] is False

        print()
        print("=== 6) remove pumps → flooded=True and capacity drops ===")
        d.journal._conn.execute("DELETE FROM pumps WHERE site_id = ?", (ug["id"],))
        util2 = procurement.site_utilization(d.journal, ug["id"])
        print(f"  flooded={util2['flooded']} cap={util2['power_kw_capacity']}kW")
        assert util2["flooded"] is True
        assert util2["power_kw_capacity"] == 0

        print()
        print("=== 7) buy pump-system restores the site ===")
        r = procurement.buy(d.journal, d.scheduler.add, "pump-system-sm",
                            target_site_id=ug["id"])
        procurement.on_install_complete(d.journal, r["purchase_id"])
        util3 = procurement.site_utilization(d.journal, ug["id"])
        print(f"  after install: flooded={util3['flooded']} cap={util3['power_kw_capacity']}kW")
        assert util3["flooded"] is False
        assert util3["power_kw_capacity"] == 100   # underground nominal

        print()
        print("=== 8) tent + bunker_shallow establish cleanly ===")
        for t in ("tent", "bunker_shallow"):
            sites.on_site_established(d.journal, t, f"Site-{t}")
        all_sites = d.journal.list_sites()
        names = [s["name"] for s in all_sites]
        print(f"  sites: {names}")
        assert any(s["name"] == "Site-tent" for s in all_sites)
        assert any(s["name"] == "Site-bunker_shallow" for s in all_sites)

        st.cancel()
        try:
            await st
        except (asyncio.CancelledError, Exception):
            pass
        d.journal.close()
        print()
        print("---PHASE 7 TESTS PASSED---")
    finally:
        time.sleep(0.2)
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test())
