import asyncio
import shutil
import tempfile
import time
from pathlib import Path

from scp.daemon import gameplay, outages, procurement
from scp.daemon.hardware import catalog as hw
from scp.daemon.main import Daemon


async def test():
    td = Path(tempfile.mkdtemp())
    try:
        d = Daemon(db_path=td / "p5b.db", port=53800)
        gameplay.bootstrap_if_empty(d.journal)
        d.scheduler.rehydrate()
        await d.ipc.start()
        st = asyncio.create_task(d.scheduler.run())
        d.journal.set_funding(100_000_000)

        print("=== 1) battery + fuel storage SKUs present ===")
        batteries = [s for s in hw.SKUS.values() if s.category == "battery_bank"]
        fuel = [s for s in hw.SKUS.values() if s.category == "fuel_storage"]
        print(f"  batteries: {len(batteries)}  fuel_storage: {len(fuel)}")
        assert len(batteries) >= 3
        assert len(fuel) >= 3

        print()
        print("=== 2) bootstrap site ships with resilience ===")
        res = d.journal.get_site_resilience(1)
        print(f"  initial: battery={res['battery_kwh']} kWh  fuel={res['fuel_hours']} h")
        assert res["battery_kwh"] > 0
        assert res["fuel_hours"] > 0

        print()
        print("=== 3) install UPS bumps battery capacity ===")
        r = procurement.buy(d.journal, d.scheduler.add, "ups-rack")
        procurement.on_install_complete(d.journal, r["purchase_id"])
        res2 = d.journal.get_site_resilience(1)
        print(f"  after ups-rack: battery={res2['battery_kwh']} kWh")
        assert res2["battery_kwh"] == res["battery_kwh"] + 5

        r = procurement.buy(d.journal, d.scheduler.add, "battery-bank-200")
        procurement.on_install_complete(d.journal, r["purchase_id"])
        res3 = d.journal.get_site_resilience(1)
        print(f"  after 200 kWh bank: battery={res3['battery_kwh']} kWh")
        assert res3["battery_kwh"] == res2["battery_kwh"] + 200

        print()
        print("=== 4) install fuel tank bumps fuel hours ===")
        r = procurement.buy(d.journal, d.scheduler.add, "fuel-tank-med")
        procurement.on_install_complete(d.journal, r["purchase_id"])
        res4 = d.journal.get_site_resilience(1)
        print(f"  after fuel-tank-med: fuel={res4['fuel_hours']} h")
        assert res4["fuel_hours"] == res["fuel_hours"] + 72

        print()
        print("=== 5) ride-through computed in site_utilization ===")
        util = procurement.site_utilization(d.journal, 1)
        print(
            f"  battery={util['battery_kwh']} kWh  fuel={util['fuel_hours']} h  "
            f"ride≈{util['ride_through_hours']} h  load={util['power_kw_used']} kW"
        )
        assert util["ride_through_hours"] > 100  # lots of battery + fuel

        print()
        print("=== 6) trigger 2h outage: ride-through succeeds ===")
        r = outages.trigger_manual_outage(
            d.journal, d.scheduler.add, site_id=1, duration_h=2.0
        )
        print(f"  outage triggered: ride_through={r['ride_through']}")
        assert r["ride_through"] is True
        util = procurement.site_utilization(d.journal, 1)
        print(f"  during ride-through outage: outaged={util['outaged']}")
        assert util["outaged"] is False  # ride-through means site stays up

        print()
        print("=== 7) trigger huge outage: site goes dark ===")
        # Remove resilience, force dark
        d.journal._conn.execute("DELETE FROM site_resilience WHERE site_id=1")
        r = outages.trigger_manual_outage(
            d.journal, d.scheduler.add, site_id=1, duration_h=8.0
        )
        print(f"  outage triggered: ride_through={r['ride_through']}")
        assert r["ride_through"] is False
        util = procurement.site_utilization(d.journal, 1)
        print(
            f"  site dark: capacity={util['power_kw_capacity']} "
            f"outaged={util['outaged']}"
        )
        assert util["outaged"] is True
        assert util["power_kw_capacity"] == 0

        print()
        print("=== 8) outage roll cadence (scheduled by Daemon.run) ===")
        # Bypass: this test uses scheduler.run() directly; normally Daemon.run
        # queues the first outage_roll on startup. Simulate that here.
        outages.schedule_next_roll(d.scheduler.add)
        pending = d.journal.pending()
        has_roll = any(p["kind"] == "outage_roll" for p in pending)
        print(f"  outage_roll queued: {has_roll}")
        assert has_roll

        st.cancel()
        try:
            await st
        except (asyncio.CancelledError, Exception):
            pass
        d.journal.close()
        print()
        print("---PHASE 5B TESTS PASSED---")
    finally:
        time.sleep(0.2)
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test())
