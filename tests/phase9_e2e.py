import asyncio
import shutil
import tempfile
import time
from pathlib import Path

from scp.daemon import gameplay, payroll, recruitment
from scp.daemon.main import Daemon


async def test():
    td = Path(tempfile.mkdtemp())
    try:
        d = Daemon(db_path=td / "p9.db", port=54500)
        gameplay.bootstrap_if_empty(d.journal)
        d.scheduler.rehydrate()
        await d.ipc.start()
        st = asyncio.create_task(d.scheduler.run())
        d.journal.set_funding(10_000_000)

        print("=== 1) role catalog ===")
        roles = recruitment.list_roles()
        print(f"  {len(roles)} roles")
        for r in roles:
            print(
                f"  {r.role_id:22s} recruit=${r.recruit_cost_usd:>8,} "
                f"salary=${r.annual_salary_usd:>8,}/yr clearance=L{r.clearance}"
            )
        assert len(roles) >= 8
        assert any(r.role_id == "reactor_operator" for r in roles)

        print()
        print("=== 2) recruit an analyst ===")
        import random
        rng = random.Random(7)
        r = recruitment.recruit(d.journal, d.scheduler.add, "analyst", rng)
        print(f"  ordered: {r['candidate_name']} ({r['role_id']}) "
              f"ETA {r['eta']} balance ${r['balance']:,}")
        assert r["role_id"] == "analyst"
        before_roster = len(d.journal.list_staff())

        # Fast-forward: fire the pending hire_complete
        pending = d.journal.pending()
        hire_events = [p for p in pending if p["kind"] == "hire_complete"]
        assert hire_events
        result = recruitment.on_hire_complete(
            d.journal,
            role_id=hire_events[0]["payload"]["role_id"],
            candidate_name=hire_events[0]["payload"]["candidate_name"],
            target_site_id=hire_events[0]["payload"]["target_site_id"],
        )
        print(f"  hired: staff {result['staff_id']} {result['name']} "
              f"${result['annual_salary']:,}/yr")
        after_roster = d.journal.list_staff()
        assert len(after_roster) == before_roster + 1
        new_hire = next(s for s in after_roster if s["id"] == result["staff_id"])
        print(f"  clearance=L{new_hire['clearance']} skills={new_hire['skills']}")
        assert new_hire["salary"] == 120_000
        assert new_hire["is_player"] is False

        print()
        print("=== 3) insufficient funding refuses recruit ===")
        d.journal.set_funding(100)
        try:
            recruitment.recruit(d.journal, d.scheduler.add, "memeticist_sr", rng)
            assert False
        except ValueError as e:
            print(f"  PASS: {e}")

        print()
        print("=== 4) unknown role rejected ===")
        d.journal.set_funding(10_000_000)
        try:
            recruitment.recruit(d.journal, d.scheduler.add, "wizard", rng)
            assert False
        except ValueError as e:
            print(f"  PASS: {e}")

        print()
        print("=== 5) payroll run deducts weekly wages ===")
        balance_before = d.journal.get_funding()
        result = payroll.on_payroll_run(d.journal, d.scheduler.add)
        print(f"  staff paid: {result['staff_paid']} (player excluded)")
        print(f"  weekly total: ${result['weekly_total']:,}")
        print(f"  balance: ${balance_before:,} -> ${result['balance_after']:,}")
        # 3 bootstrap staff: player (excluded) + Dr. Vey (120k/yr) + Tech Osei (90k/yr)
        # + the analyst we just hired (120k/yr)
        # = (120000 + 90000 + 120000) / 52 = 6346
        # Pre-hire only 2 NPCs would give 4038. After hire, 3 NPCs -> 6346.
        # Per-staff integer division (truncated each), summed:
        expected = (120_000 // 52) + (90_000 // 52) + (120_000 // 52)
        print(f"  expected weekly: ${expected:,}")
        assert result["weekly_total"] == expected

        # Next payroll is queued
        pending = d.journal.pending()
        assert any(p["kind"] == "payroll_run" for p in pending)
        print("  PASS: next payroll_run queued")

        print()
        print("=== 6) payroll shortfall triggers ALERT ===")
        d.journal.set_funding(1_000)   # can't cover weekly
        result = payroll.on_payroll_run(d.journal, d.scheduler.add)
        assert result["shortfall"] is True
        print(f"  PASS: shortfall detected; balance now ${result['balance_after']:,}")

        st.cancel()
        try:
            await st
        except (asyncio.CancelledError, Exception):
            pass
        d.journal.close()
        print()
        print("---PHASE 9 TESTS PASSED---")
    finally:
        time.sleep(0.2)
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test())
