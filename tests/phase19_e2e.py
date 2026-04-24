"""
Phase 19 — runtime time compression.

Covers:
- default multiplier = 1.0
- set_time_multiplier clamps to [0.0001, 10_000.0]
- scheduler fires events proportionally faster under compression
- speed change takes effect on in-flight sleeps (doesn't wait for the
  current sleep to complete before applying)
- sitrep exposes the multiplier
- IPC verb GET + SET round-trips and wakes the scheduler
"""
import asyncio
import json
import shutil
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from scp.daemon import gameplay
from scp.daemon.clock import now_utc
from scp.daemon.main import Daemon
from scp.tui.client import DaemonClient


async def test():
    td = Path(tempfile.mkdtemp())
    try:
        d = Daemon(db_path=td / "p19.db", port=54919)
        gameplay.bootstrap_if_empty(d.journal)
        d.scheduler.rehydrate()
        await d.ipc.start()
        st = asyncio.create_task(d.scheduler.run())

        print("=== 1) default multiplier is 1.0× ===")
        assert d.journal.get_time_multiplier() == 1.0
        print("  OK")

        print()
        print("=== 2) set/clamp ===")
        assert d.journal.set_time_multiplier(100) == 100.0
        assert d.journal.set_time_multiplier(99_999_999) == 10_000.0
        assert d.journal.set_time_multiplier(-5) == 0.0001
        d.journal.set_time_multiplier(1.0)  # reset
        print("  clamped high+low, reset to 1.0  OK")

        print()
        print("=== 3) 60s event fires quickly at 100× ===")
        d.journal.set_time_multiplier(100.0)
        d.scheduler._wake.set()

        fired: list[float] = []

        async def on_fire(sid, kind, payload):
            fired.append(time.time())

        original_hook = d.scheduler._fire_hook
        d.scheduler._fire_hook = on_fire

        t0 = time.time()
        eta = now_utc() + timedelta(seconds=60)
        d.scheduler.add(eta, "compression_test_a", {})
        for _ in range(40):  # up to 4s
            if fired:
                break
            await asyncio.sleep(0.1)
        real_elapsed = (fired[0] - t0) if fired else -1
        assert fired, "event did not fire within 4s"
        # 60 / 100 = 0.6s theoretical. Allow generous slack for jitter.
        assert 0.3 <= real_elapsed <= 3.0, (
            f"expected ~0.6s, got {real_elapsed:.2f}s"
        )
        print(f"  60s event fired in {real_elapsed:.2f}s real (at 100×)  OK")

        print()
        print("=== 4) speed change mid-sleep re-applies ===")
        # Schedule 300s out at 1×, then switch to 1000× — event should fire
        # within a couple of seconds thanks to the 60s sleep cap + re-check.
        d.journal.set_time_multiplier(1.0)
        d.scheduler._wake.set()
        await asyncio.sleep(0.2)

        fired.clear()
        t0 = time.time()
        eta2 = now_utc() + timedelta(seconds=300)
        d.scheduler.add(eta2, "compression_test_b", {})
        # Wait a moment at 1× (should NOT fire)
        await asyncio.sleep(0.5)
        assert not fired, "event should not fire at 1× within 0.5s"
        # Now crank to 1000×
        d.journal.set_time_multiplier(1000.0)
        d.scheduler._wake.set()
        for _ in range(30):
            if fired:
                break
            await asyncio.sleep(0.1)
        real_elapsed2 = (fired[0] - t0) if fired else -1
        assert fired, "event didn't fire after speed change"
        # 300 / 1000 = 0.3s theoretical after the 0.5s initial wait = ~0.8s total
        # but we could have been mid-sleep when speed changed, and the 60s cap
        # means we re-check within 60s real. In practice re-check happens from
        # wake.set(), so it should be very fast.
        print(f"  300s event fired {real_elapsed2:.2f}s after speed change  OK")
        assert real_elapsed2 < 3.0

        d.scheduler._fire_hook = original_hook

        print()
        print("=== 5) sitrep exposes the multiplier ===")
        d.journal.set_time_multiplier(25.0)
        sit = gameplay.sitrep(d.journal)
        assert sit["time_multiplier"] == 25.0
        print(f"  sitrep.time_multiplier = {sit['time_multiplier']}  OK")

        print()
        print("=== 6) IPC time_multiplier GET + SET ===")
        client = DaemonClient("127.0.0.1", 54919)
        await client.connect()
        get_reply = await client.send({"type": "time_multiplier"})
        assert get_reply["payload"]["multiplier"] == 25.0

        set_reply = await client.send(
            {"type": "time_multiplier", "payload": {"value": 5.0}}
        )
        assert set_reply["payload"]["multiplier"] == 5.0
        assert set_reply["payload"]["before"] == 25.0
        assert d.journal.get_time_multiplier() == 5.0
        await client.close()
        print(f"  IPC round-trip: 25× → 5×  OK")

        st.cancel()
        try:
            await st
        except (asyncio.CancelledError, Exception):
            pass
        d.journal.close()
        print()
        print("---PHASE 19 TESTS PASSED---")
    finally:
        time.sleep(0.2)
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test())
