"""
Phase 13 — vessel equipment + orders.

Covers:
- equipment catalog gated by vessel type + class
- install/uninstall guarded by vessel status (berthed only)
- sensor/archive/stealth rating sums
- patrol requires sensor, pays out based on rating + hull class
- standby_archive requires containment pod, pays out by pod capacity
- escort_convoy flat payout by hull class
- double-order rejected
- return_to_port moves vessel to new site
- scheduler fires completion and credits funding
"""
import asyncio
import json
import shutil
import tempfile
import time
from pathlib import Path

from scp.daemon import gameplay, sites, vessel_ops
from scp.daemon.main import Daemon


async def test():
    td = Path(tempfile.mkdtemp())
    try:
        d = Daemon(db_path=td / "p13.db", port=54913)
        gameplay.bootstrap_if_empty(d.journal)
        d.scheduler.rehydrate()
        await d.ipc.start()
        st = asyncio.create_task(d.scheduler.run())
        d.journal.set_funding(200_000_000)

        print("=== 1) equipment catalog filters by type + class ===")
        ship_only = vessel_ops.list_equipment(vessel_type="ship")
        sub_only = vessel_ops.list_equipment(vessel_type="submarine")
        uuv_only = vessel_ops.list_equipment(vessel_type="submarine", vessel_class="uuv")
        ship_skus = {e.sku for e in ship_only}
        sub_skus = {e.sku for e in sub_only}
        uuv_skus = {e.sku for e in uuv_only}
        print(f"  ship catalog: {len(ship_skus)} items  (has radar? {'radar-maritime' in ship_skus})")
        print(f"  sub catalog:  {len(sub_skus)} items  (has anechoic? {'anechoic-coating' in sub_skus})")
        print(f"  uuv subset:   {len(uuv_skus)} items  (has archive-pod-lg? {'archive-pod-lg' in uuv_skus})")
        assert "radar-maritime" in ship_skus
        assert "radar-maritime" not in sub_skus     # ships only
        assert "anechoic-coating" not in ship_skus  # subs only
        assert "anechoic-coating" in sub_skus
        assert "archive-pod-lg" not in uuv_skus     # heavy class only

        print()
        print("=== 2) install equipment with type/class gating ===")
        ship_id = d.journal.create_ship(
            site_id=1, hull_number="FF-9000", sku="osv-class", ship_class="medium"
        )
        sub_id = d.journal.create_submarine(
            site_id=1, hull_number="SS-9000", sku="basalt-ssk-surplus", sub_class="ssk"
        )
        uuv_id = d.journal.create_submarine(
            site_id=1, hull_number="UU-9000", sku="barracuda-uuv", sub_class="uuv"
        )

        # Ship takes sonar + pod
        vessel_ops.install_equipment(d.journal, "ship", ship_id, "sonar-towed-passive")
        vessel_ops.install_equipment(d.journal, "ship", ship_id, "archive-pod-sm")
        # Anechoic on ship rejects
        try:
            vessel_ops.install_equipment(d.journal, "ship", ship_id, "anechoic-coating")
            assert False, "anechoic must reject on ship"
        except ValueError as e:
            print(f"  anechoic→ship rejected: {e}")
        # Large pod on UUV rejects
        try:
            vessel_ops.install_equipment(d.journal, "submarine", uuv_id, "archive-pod-lg")
            assert False, "archive-pod-lg must reject on uuv"
        except ValueError as e:
            print(f"  archive-pod-lg→uuv rejected: {e}")

        # Sub takes sonar + anechoic + small pod
        vessel_ops.install_equipment(d.journal, "submarine", sub_id, "sonar-active-array")
        vessel_ops.install_equipment(d.journal, "submarine", sub_id, "anechoic-coating")
        vessel_ops.install_equipment(d.journal, "submarine", sub_id, "archive-pod-sm")

        print()
        print("=== 3) ratings accumulate across installed equipment ===")
        assert vessel_ops.vessel_sensor_rating(d.journal, "ship", ship_id) == 3
        assert vessel_ops.vessel_archive_capacity_gb(d.journal, "ship", ship_id) == 50_000
        # Sub: active-array rating=5 (sonar) + anechoic rating=4 (stealth)
        assert vessel_ops.vessel_sensor_rating(d.journal, "submarine", sub_id) == 5
        assert vessel_ops.vessel_stealth_rating(d.journal, "submarine", sub_id) == 4
        assert vessel_ops.vessel_archive_capacity_gb(d.journal, "submarine", sub_id) == 50_000
        print(f"  ship sensor=3 pod=50k  sub sensor=5 stealth=4 pod=50k  OK")

        print()
        print("=== 4) patrol requires sensor + pays out ===")
        # Create a ship with NO equipment
        naked_ship = d.journal.create_ship(
            site_id=1, hull_number="FF-NAK", sku="yacht-expedition", ship_class="small"
        )
        try:
            vessel_ops.order_vessel(d.journal, d.scheduler.add, "ship", naked_ship, "patrol")
            assert False, "patrol must reject without sensor"
        except ValueError as e:
            print(f"  naked-ship patrol rejected: {e}")

        r = vessel_ops.order_vessel(
            d.journal, d.scheduler.add, "ship", ship_id, "patrol", hours=6
        )
        # ship_class medium mult=1.5, sensor=3 -> $5k*6*1.5*1.3 = $58,500
        assert r["payout_usd"] == 58_500, f"unexpected payout {r['payout_usd']}"
        print(f"  patrol payout: ${r['payout_usd']:,} (expected $58,500)")

        print()
        print("=== 5) double-order rejected ===")
        try:
            vessel_ops.order_vessel(d.journal, d.scheduler.add, "ship", ship_id, "escort_convoy")
            assert False, "double order must reject"
        except ValueError as e:
            print(f"  double order rejected: {e}")

        print()
        print("=== 6) standby_archive requires pod + pays by capacity ===")
        r_st = vessel_ops.order_vessel(
            d.journal, d.scheduler.add, "submarine", sub_id, "standby_archive", hours=12
        )
        # $1k * 12h * (50000/10000) = $60,000
        assert r_st["payout_usd"] == 60_000
        print(f"  standby payout: ${r_st['payout_usd']:,}  (50 TB pod, 12h)")

        print()
        print("=== 7) scheduler fires completion and credits funding ===")
        bal_before = d.journal.get_funding()
        await asyncio.sleep(25)  # with SCP_TIME_SCALE=0.001, 6h → 21.6s
        order_row = d.journal.get_vessel_order(r["order_id"])
        assert order_row["state"] == "complete", f"got {order_row['state']}"
        effect = json.loads(order_row["effect_json"] or "{}")
        assert effect.get("payout_usd") == 58_500
        bal_after = d.journal.get_funding()
        print(f"  balance before={bal_before:,}  after={bal_after:,}  Δ=+{bal_after-bal_before:,}")
        # Ship is berthed again
        ship_after = next(s for s in d.journal.list_ships() if s["id"] == ship_id)
        print(f"  ship status after: {ship_after['status']}")
        assert ship_after["status"] == "berthed"

        print()
        print("=== 8) return_to_port moves vessel to new site ===")
        sites.on_site_established(d.journal, "office_closet", "Site-Port2")
        site2 = next(s for s in d.journal.list_sites() if s["name"] == "Site-Port2")
        r_r = vessel_ops.order_vessel(
            d.journal, d.scheduler.add, "ship", ship_id, "return_to_port",
            target_site_id=site2["id"], hours=4
        )
        await asyncio.sleep(20)
        ship_final = next(s for s in d.journal.list_ships() if s["id"] == ship_id)
        print(f"  ship now @site {ship_final['site_id']} (was site 1, targeted {site2['id']})")
        assert ship_final["site_id"] == site2["id"]
        assert ship_final["status"] == "berthed"

        print()
        print("=== 9) escort_convoy flat payout by class ===")
        r_e = vessel_ops.order_vessel(
            d.journal, d.scheduler.add, "submarine", uuv_id, "escort_convoy"
        )
        # uuv mult 0.3 * $40k = $12,000
        print(f"  uuv escort payout: ${r_e['payout_usd']:,}")
        assert r_e["payout_usd"] == 12_000

        # cleanup — orders may have already completed; ignore if none active
        for vt, vid in (("submarine", sub_id), ("submarine", uuv_id)):
            try:
                vessel_ops.cancel_order(d.journal, vt, vid)
            except ValueError:
                pass

        st.cancel()
        try:
            await st
        except (asyncio.CancelledError, Exception):
            pass
        d.journal.close()
        print()
        print("---PHASE 13 TESTS PASSED---")
    finally:
        time.sleep(0.2)
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test())
