import asyncio
import shutil
import tempfile
import time
from pathlib import Path

from scp.daemon import contracts, gameplay, procurement, sites
from scp.daemon.content.items import ItemProfile
from scp.daemon.hardware import catalog as hw
from scp.daemon.main import Daemon


async def test():
    td = Path(tempfile.mkdtemp())
    try:
        d = Daemon(db_path=td / "p4.db", port=53500)
        gameplay.bootstrap_if_empty(d.journal)
        d.scheduler.rehydrate()
        await d.ipc.start()
        st = asyncio.create_task(d.scheduler.run())
        d.journal.set_funding(10_000_000_000)

        print("=== 1) Payload diversity ===")
        payload_skus = [s for s in hw.SKUS.values() if s.category == "satellite"]
        payloads = sorted({s.capabilities.get("payload") for s in payload_skus})
        print(f"  payloads: {payloads}")
        assert set(payloads) >= {"comms", "compute", "imint", "sigint", "storage", "otv"}

        for sku in ["nimbus-storage", "nimbus-compute", "cubesat-sigint-3u"]:
            r = procurement.buy(d.journal, d.scheduler.add, sku)
            procurement.on_install_complete(d.journal, r["purchase_id"])
        roster = d.journal.list_satellites()
        print(f"  on-orbit: {[(s['callsign'], s['payload']) for s in roster]}")

        print()
        print("=== storage sat boosts archive reward by 25% ===")
        d.journal.update_staff_skills(1, {"infosec": 90, "memetics": 50, "forensics": 20})
        d.journal.update_vm_spec(1, {
            "memory_encryption": 10, "isolation": 8, "mnestic_firmware": 4,
            "physical_shielding": 6, "scanner_freshness": 2,
        })
        d.journal.set_site_encryption(1, "type1")
        pi = ItemProfile("SCP-9601", "Safe", 3, 1, 0, 0, "t", "t")
        iid = d.journal.create_item(pi.designation, pi.item_class, pi.hazard_strength, pi.to_dict())
        gameplay.acquire_candidate(d.journal, iid)
        gameplay.start_analyze(d.journal, d.scheduler.add, iid, 1)
        await asyncio.sleep(0.3)
        b_before = d.journal.get_funding()
        gameplay.start_archive(d.journal, d.scheduler.add, iid)
        await asyncio.sleep(0.5)
        reward = d.journal.get_funding() - b_before
        print(f"  reward: ${reward:,} (expected 62,500)")
        assert reward == 62_500

        print()
        print("=== sigint sat expands scan upper bound ===")
        r = gameplay.on_scan_complete(d.journal, d.rng)
        print(f"  scan found {r['count']} (upper bound now 4)")
        assert 1 <= r["count"] <= 4

        print()
        print("=== 2) OTV gated — needs GEO sat first ===")
        try:
            procurement.buy(d.journal, d.scheduler.add, "otv-class")
            assert False
        except ValueError as e:
            print(f"  PASS: {e}")
        r = procurement.buy(d.journal, d.scheduler.add, "polaris-geo-comms")
        procurement.on_install_complete(d.journal, r["purchase_id"])
        r = procurement.buy(d.journal, d.scheduler.add, "otv-class")
        ir = procurement.on_install_complete(d.journal, r["purchase_id"])
        print(f"  OTV launched: {ir.get('callsign')}")
        assert "SCP-OTV" in ir["callsign"]

        print()
        print("=== 3) Exotic sites ===")
        for t in ["subsea_pod", "underground", "antarctica"]:
            sites.on_site_established(d.journal, t, f"Site-{t}")
        all_sites = d.journal.list_sites()
        print(f"  sites: {[s['name'] for s in all_sites]}")
        assert len(all_sites) >= 4

        print()
        print("=== 4) Submarine market ===")
        r = procurement.buy(d.journal, d.scheduler.add, "small_port")
        procurement.on_install_complete(d.journal, r["purchase_id"])
        try:
            procurement.buy(d.journal, d.scheduler.add, "basalt-ssk-surplus")
            assert False
        except ValueError as e:
            print(f"  basalt refused: {e}")
        r = procurement.buy(d.journal, d.scheduler.add, "barracuda-uuv")
        ir = procurement.on_install_complete(d.journal, r["purchase_id"])
        print(f"  Barracuda UUV: {ir.get('hull_number')}")
        assert len(d.journal.list_submarines()) == 1

        try:
            procurement.buy(d.journal, d.scheduler.add, "typhoon-conversion")
            assert False
        except ValueError as e:
            print(f"  typhoon gated: {e}")

        print()
        print("=== 5) jet_a_supply lapse grounds aircraft ===")
        r = procurement.buy(d.journal, d.scheduler.add, "dirt_strip")
        procurement.on_install_complete(d.journal, r["purchase_id"])
        r = procurement.buy(d.journal, d.scheduler.add, "caesna-182")
        ir = procurement.on_install_complete(d.journal, r["purchase_id"])
        aircraft_id = ir["aircraft_id"]
        sr = contracts.subscribe(
            d.journal, d.scheduler.add, "jet_a_supply", target_asset_id=aircraft_id
        )
        d.journal.set_funding(0)
        c = d.journal.list_contracts(status="active", contract_type="jet_a_supply")[0]
        contracts.on_billing(d.journal, d.scheduler.add, c["id"])
        ac = d.journal.list_aircraft()[0]
        print(f"  aircraft after lapse: {ac['status']}")
        assert ac["status"] == "maintenance"

        print()
        print("=== 6) bunker_fuel lapse grounds ship ===")
        d.journal.set_funding(100_000_000)
        r = procurement.buy(d.journal, d.scheduler.add, "yacht-expedition")
        ir = procurement.on_install_complete(d.journal, r["purchase_id"])
        ship_id = ir["ship_id"]
        contracts.subscribe(
            d.journal, d.scheduler.add, "bunker_fuel", target_asset_id=ship_id
        )
        d.journal.set_funding(0)
        c = d.journal.list_contracts(status="active", contract_type="bunker_fuel")[0]
        contracts.on_billing(d.journal, d.scheduler.add, c["id"])
        sh = d.journal.list_ships()[0]
        print(f"  ship after lapse: {sh['status']}")
        assert sh["status"] == "maintenance"

        st.cancel()
        try:
            await st
        except asyncio.CancelledError:
            pass
        d.journal.close()
        print()
        print("---PHASE 4 TESTS PASSED: all 6 systems functional---")
    finally:
        time.sleep(0.2)
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test())
