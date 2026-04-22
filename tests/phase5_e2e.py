import asyncio
import json
import shutil
import tempfile
import time
from pathlib import Path

from scp.daemon import gameplay, procurement
from scp.daemon.hardware import catalog as hw
from scp.daemon.main import Daemon


async def test():
    td = Path(tempfile.mkdtemp())
    try:
        d = Daemon(db_path=td / "p5.db", port=53700)
        gameplay.bootstrap_if_empty(d.journal)
        d.scheduler.rehydrate()
        await d.ipc.start()
        st = asyncio.create_task(d.scheduler.run())
        d.journal.set_funding(10_000_000_000)

        print("=== 1) aircraft catalog coverage ===")
        ac_skus = [s for s in hw.SKUS.values() if s.category == "aircraft"]
        requested = {
            "twin-utility", "galaxy-5", "titanlift-17",
            "spyglass-u2", "blackbird-71",
            "lightning-35", "raptor-22", "phantom-47",
            "oceanhawk-mpa", "skywatch-awacs", "rivergaze-rc135",
        }
        have = {s.sku for s in ac_skus}
        missing = requested - have
        print(f"  {len(ac_skus)} aircraft SKUs. missing from request: {missing or 'none'}")
        assert not missing

        print()
        print("=== 2) military stealth airframe gate ===")
        # Need an airfield to buy any aircraft
        r = procurement.buy(d.journal, d.scheduler.add, "dirt_strip")
        procurement.on_install_complete(d.journal, r["purchase_id"])
        r = procurement.buy(d.journal, d.scheduler.add, "small_airport")
        procurement.on_install_complete(d.journal, r["purchase_id"])
        # F-47 requires 2 prior stealth airframes
        try:
            procurement.buy(d.journal, d.scheduler.add, "phantom-47")
            assert False
        except ValueError as e:
            print(f"  phantom-47 gated: {e}")
        # Buy F-22 + F-35 first
        for sku in ["raptor-22", "lightning-35"]:
            r = procurement.buy(d.journal, d.scheduler.add, sku)
            procurement.on_install_complete(d.journal, r["purchase_id"])
        # Now install private_airfield for F-47
        r = procurement.buy(d.journal, d.scheduler.add, "private_airfield")
        procurement.on_install_complete(d.journal, r["purchase_id"])
        r = procurement.buy(d.journal, d.scheduler.add, "phantom-47")
        ir = procurement.on_install_complete(d.journal, r["purchase_id"])
        print(f"  phantom-47 cleared gate: {ir.get('tail_number')}")

        print()
        print("=== 3) ISR gate for SR-71 ===")
        try:
            procurement.buy(d.journal, d.scheduler.add, "blackbird-71")
            assert False
        except ValueError as e:
            print(f"  SR-71 gated: {e}")
        # Buy 2 ISR aircraft (u-2 + oceanhawk)
        for sku in ["spyglass-u2", "oceanhawk-mpa"]:
            r = procurement.buy(d.journal, d.scheduler.add, sku)
            procurement.on_install_complete(d.journal, r["purchase_id"])
        r = procurement.buy(d.journal, d.scheduler.add, "blackbird-71")
        ir = procurement.on_install_complete(d.journal, r["purchase_id"])
        print(f"  SR-71 cleared gate: {ir.get('tail_number')}")

        print()
        print("=== 4) submarine additions ===")
        subs = [s for s in hw.SKUS.values() if s.category == "submarine"]
        expected = {
            "mako-type209", "stingray-aip-type214", "scorpion-class",
            "shark-ssn-surplus", "foxglove-surplus",
        }
        missing = expected - {s.sku for s in subs}
        print(f"  {len(subs)} submarines. missing: {missing or 'none'}")
        assert not missing

        print()
        print("=== 5) Panthalassa products ===")
        panth = [s for s in hw.SKUS.values() if s.sku.startswith("panthalassa-")]
        print(f"  {len(panth)} Panthalassa SKUs: {[s.sku for s in panth]}")
        assert len(panth) >= 3

        print()
        print("=== 6) power plants — install bumps site capacity ===")
        cap_before = procurement.site_utilization(d.journal, 1)["power_kw_capacity"]
        print(f"  site 1 power capacity before: {cap_before} kW")
        r = procurement.buy(d.journal, d.scheduler.add, "diesel-genset-md")
        procurement.on_install_complete(d.journal, r["purchase_id"])
        cap_after = procurement.site_utilization(d.journal, 1)["power_kw_capacity"]
        print(f"  after 100 kW genset: {cap_after} kW")
        assert cap_after == cap_before + 100

        # Microreactor stacks
        r = procurement.buy(d.journal, d.scheduler.add, "kilopower-micro")
        procurement.on_install_complete(d.journal, r["purchase_id"])
        cap_after2 = procurement.site_utilization(d.journal, 1)["power_kw_capacity"]
        print(f"  after +10 kW micro-reactor: {cap_after2} kW")
        assert cap_after2 == cap_after + 10

        plants = d.journal.list_power_plants(1)
        print(f"  power_plants at site 1: {[(p['plant_type'], p['kw_rating']) for p in plants]}")
        assert len(plants) == 2

        print()
        print("=== 7) reactor_operator course ===")
        from scp.daemon import training
        c = training.get("reactor_operator")
        print(f"  course: {c.name}, skill={c.skill}+{c.skill_gain}, cost=${c.cost_usd:,}")
        assert c.skill == "reactor_operator"

        # Clean up the hand-rolled scheduler task from earlier tests
        st.cancel()
        try:
            await st
        except (asyncio.CancelledError, Exception):
            pass
        d.journal.close()

        print()
        print("=== 8) daemon shutdown via IPC (fresh Daemon.run) ===")
        d2 = Daemon(db_path=td / "p5b.db", port=53701)
        run_task = asyncio.create_task(d2.run())
        # Give Daemon.run a moment to bootstrap + start IPC
        await asyncio.sleep(0.3)
        reader, writer = await asyncio.open_connection("127.0.0.1", 53701)
        writer.write(b'{"type":"shutdown"}\n')
        await writer.drain()
        reply = json.loads((await reader.readline()).decode())
        print(f"  reply: {reply}")
        assert reply["type"] == "ack"
        assert reply["payload"]["shutting_down"] is True
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

        # Daemon.run() should exit within a second of receiving shutdown
        try:
            await asyncio.wait_for(run_task, timeout=3.0)
            print("  daemon.run() returned cleanly")
        except asyncio.TimeoutError:
            run_task.cancel()
            try:
                await run_task
            except Exception:
                pass
            raise AssertionError("daemon did not shut down within 3s")
        d2.journal.close()

        print()
        print("---PHASE 5 TESTS PASSED---")
    finally:
        time.sleep(0.2)
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test())
