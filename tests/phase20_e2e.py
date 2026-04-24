"""
Phase 20 — intel groundwork (rival GOI detection).

Covers:
- seed_rivals_if_empty populates the catalog on first boot
- rival_sites table queryable by region + goi_id
- estimate_power reports base + asset + site-security bonuses
- dispatch_mission rejects unknown kinds / regions / missing HUMINT asset
- aircraft ISR bonus matches kind (sigint/elint/imint)
- staff humint bonus scales with infosec skill
- scheduler fires intel_mission_complete and advances contact state
- contact states progress: unknown → rumored → located → cataloged
- IPC verbs round-trip: intel_rivals, intel_contacts, intel_missions,
  dispatch_intel_mission, estimate_intel_power
"""
import asyncio
import random
import shutil
import tempfile
import time
from pathlib import Path

from scp.daemon import gameplay, intel
from scp.daemon.main import Daemon
from scp.tui.client import DaemonClient


async def test():
    td = Path(tempfile.mkdtemp())
    try:
        d = Daemon(db_path=td / "p20.db", port=54920)
        gameplay.bootstrap_if_empty(d.journal)
        d.scheduler.rehydrate()
        await d.ipc.start()
        st = asyncio.create_task(d.scheduler.run())
        d.journal.set_funding(10_000_000_000)

        print("=== 1) rivals seed on first boot ===")
        n = intel.seed_rivals_if_empty(d.journal)
        assert n == len(intel.SITE_TEMPLATES)
        # Second call is idempotent
        assert intel.seed_rivals_if_empty(d.journal) == 0
        rivals = d.journal.list_rival_sites()
        assert len(rivals) == len(intel.SITE_TEMPLATES)
        print(f"  {len(rivals)} rival sites seeded (idempotent)  OK")

        print()
        print("=== 2) rival_sites queryable by region + goi_id ===")
        euro = d.journal.list_rival_sites(region="europe")
        assert all(r["region"] == "europe" for r in euro)
        ci = d.journal.list_rival_sites(goi_id="chaos_insurgency")
        assert all(r["goi_id"] == "chaos_insurgency" for r in ci)
        print(f"  europe={len(euro)} ci_sites={len(ci)}  OK")

        print()
        print("=== 3) estimate_power: base only, no asset ===")
        est = intel.estimate_power(d.journal, "sigint", None, None, None)
        assert est["base"] == 45
        assert est["asset_bonus"] == 0
        assert est["total"] == 45
        print(f"  sigint base-only total={est['total']}  OK")

        print()
        print("=== 4) dispatch rejects bad kind / region / humint-without-staff ===")
        try:
            intel.dispatch_mission(d.journal, d.scheduler.add,
                                   kind="psychic", region="europe")
            assert False
        except ValueError as e:
            print(f"  bad kind: {e}")
        try:
            intel.dispatch_mission(d.journal, d.scheduler.add,
                                   kind="sigint", region="mars")
            assert False
        except ValueError as e:
            print(f"  bad region: {e}")
        try:
            intel.dispatch_mission(d.journal, d.scheduler.add,
                                   kind="humint", region="europe")
            assert False
        except ValueError as e:
            print(f"  humint without staff: {e}")

        print()
        print("=== 5) humint w/ staff: power includes skill bonus ===")
        d.journal.update_staff_skills(1, {"infosec": 80})
        est_h = intel.estimate_power(
            d.journal, "humint", "staff", 1, None
        )
        # base 60 + (infosec 80 - 30) = 110
        assert est_h["asset_bonus"] == 50
        assert est_h["total"] == 110
        print(f"  humint@staff1 infosec=80 → power={est_h['total']}  OK")

        print()
        print("=== 6) aircraft ISR bonus matches kind ===")
        # Fabricate an aircraft row directly in DB (skip buy flow for isolation)
        d.journal._conn.execute(
            "INSERT INTO site_airfield (site_id, tier) VALUES (1, 'small_airport')"
        )
        ac_id = d.journal._conn.execute(
            "INSERT INTO aircraft (site_id, tail_number, sku, aircraft_class, "
            "status, purchased_at) VALUES (1, 'SCP-OH01', 'oceanhawk-mpa', "
            "'fixed_wing', 'ready', ?)",
            (intel.iso(intel.now_utc()),),
        ).lastrowid
        est_s = intel.estimate_power(d.journal, "sigint", "aircraft", ac_id, None)
        assert est_s["asset_bonus"] == 20    # oceanhawk has isr_type=sigint
        est_i = intel.estimate_power(d.journal, "imint", "aircraft", ac_id, None)
        assert est_i["asset_bonus"] == 0     # oceanhawk isn't an imint asset
        print(f"  oceanhawk sigint bonus=20, imint bonus=0  OK")

        print()
        print("=== 7) mission completion advances contact state ===")
        # Wipe any existing contacts from prior test interaction
        d.journal._conn.execute("DELETE FROM intel_contacts")

        # Dispatch a high-power mission in europe
        d.rng = random.Random(11)
        res = intel.dispatch_mission(
            d.journal, d.scheduler.add,
            kind="humint", region="europe",
            asset_type="staff", asset_id=1,
        )
        # humint is 48h at default _TS but SCP_TIME_SCALE=0.001 → 172.8s real
        # flush pending bypasses the wait
        await d._flush_pending()

        contacts = d.journal.list_intel_contacts()
        print(f"  {len(contacts)} contacts after humint-europe (power 110)")
        assert len(contacts) >= 2, f"high power should hit multiple, got {len(contacts)}"
        # All should be 'rumored' (first-time contact)
        assert all(c["state"] == "rumored" for c in contacts)

        # Re-run in same region to advance some to 'located'
        d.rng = random.Random(12)
        intel.dispatch_mission(
            d.journal, d.scheduler.add,
            kind="humint", region="europe",
            asset_type="staff", asset_id=1,
        )
        await d._flush_pending()
        contacts2 = d.journal.list_intel_contacts()
        located = [c for c in contacts2 if c["state"] == "located"]
        print(f"  after 2nd run: rumored={sum(1 for c in contacts2 if c['state']=='rumored')}  "
              f"located={len(located)}")
        assert len(located) >= 1, "second pass should advance at least one contact"

        print()
        print("=== 8) IPC round-trip ===")
        client = DaemonClient("127.0.0.1", 54920)
        await client.connect()
        r1 = await client.send({"type": "intel_rivals"})
        assert len(r1["payload"]["gois"]) == 5
        assert len(r1["payload"]["regions"]) == len(intel.REGIONS)
        r2 = await client.send({"type": "intel_contacts"})
        assert r2["payload"]["total_rivals"] == len(intel.SITE_TEMPLATES)
        r3 = await client.send({"type": "intel_missions"})
        assert len(r3["payload"]["missions"]) >= 2
        r4 = await client.send({
            "type": "estimate_intel_power",
            "payload": {"kind": "elint", "asset_type": None,
                        "asset_id": None, "home_site_id": None},
        })
        assert r4["payload"]["total"] == 50   # elint base
        r5 = await client.send({
            "type": "dispatch_intel_mission",
            "payload": {"kind": "imint", "region": "africa"},
        })
        assert r5["type"] == "dispatch_intel_mission"
        assert r5["payload"]["mission_id"] > 0
        await client.close()
        print("  intel_rivals / intel_contacts / intel_missions / "
              "estimate / dispatch all round-trip  OK")

        st.cancel()
        try:
            await st
        except (asyncio.CancelledError, Exception):
            pass
        d.journal.close()
        print()
        print("---PHASE 20 TESTS PASSED---")
    finally:
        time.sleep(0.2)
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test())
