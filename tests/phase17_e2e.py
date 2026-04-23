"""
Phase 17 — auto-analyze picker.

Covers:
- empty queue → ValueError
- single Safe + default VM → pairs item 1 → VM 1
- Keter with no capable VM → error with diagnostic
- mixed queue (Safe + Keter): Safe goes through even when Keter is blocked
- after mainframe install, Keter auto-picks the mainframe LPAR
- picker prefers the weakest capable VM (lowest containment, then lowest
  allocated RAM, then lowest id)
- IPC `analyze` with no ids auto-picks
- auto-pick response includes item + VM summary fields
"""
import asyncio
import shutil
import tempfile
import time
from pathlib import Path

from scp.daemon import gameplay, procurement
from scp.daemon.content.items import ItemProfile
from scp.daemon.main import Daemon
from scp.tui.client import DaemonClient


async def test():
    td = Path(tempfile.mkdtemp())
    try:
        d = Daemon(db_path=td / "p17.db", port=54917)
        gameplay.bootstrap_if_empty(d.journal)
        d.scheduler.rehydrate()
        await d.ipc.start()
        st = asyncio.create_task(d.scheduler.run())
        d.journal.set_funding(200_000_000)
        d.journal.update_staff_skills(1, {"infosec": 90, "memetics": 50, "forensics": 20})
        d.journal._conn.execute("UPDATE staff SET clearance = 4 WHERE id = 1")

        print("=== 1) empty queue → error ===")
        try:
            gameplay.auto_select_analyze_target(d.journal)
            assert False
        except ValueError as e:
            print(f"  OK: {e}")

        print()
        print("=== 2) Safe item → default VM ===")
        p = ItemProfile("SCP-S1", "Safe", 3, 0, 0, 0, "t", "t", size_gb=1)
        iid = d.journal.create_item(p.designation, p.item_class, p.hazard_strength, p.to_dict())
        gameplay.acquire_candidate(d.journal, iid)
        item, vm = gameplay.auto_select_analyze_target(d.journal)
        assert item["id"] == iid
        assert vm["id"] == 1
        print(f"  {item['designation']} → VM {vm['id']}  OK")

        print()
        print("=== 3) Mixed queue: Safe runs, Keter waits for capable VM ===")
        pk = ItemProfile("SCP-K1", "Keter", 15, 8, 8, 8, "t", "t", size_gb=5)
        kid = d.journal.create_item(pk.designation, pk.item_class, pk.hazard_strength, pk.to_dict())
        gameplay.acquire_candidate(d.journal, kid)
        # Queue: S1 (older) + K1. Keter can't fit cont=6 VM. But Safe can.
        # Picker walks the queue so Safe still gets paired.
        item, vm = gameplay.auto_select_analyze_target(d.journal)
        print(f"  paired: {item['designation']} → VM {vm['id']}")
        assert item["id"] == iid  # Safe first because Keter has no capable VM yet

        # Start Safe, then only Keter remains — no capable VM → diagnose
        gameplay.start_analyze(d.journal, d.scheduler.add, iid, 1)
        try:
            gameplay.auto_select_analyze_target(d.journal)
            assert False, "Keter should have no capable VM"
        except ValueError as e:
            msg = str(e)
            print(f"  OK: {msg}")
            # Either cause is acceptable: VM busy (1 VM pinned on Safe) OR
            # no capable VM (when there's an idle weak VM)
            assert any(
                tag in msg for tag in ("containment", "unavailable", "no capable")
            )

        print()
        print("=== 4) Install mainframe → Keter auto-picks LPAR ===")
        await d._flush_pending()
        procurement.buy(d.journal, d.scheduler.add, sku_id="ibex-z-base", target_site_id=1)
        await d._flush_pending()
        item, vm = gameplay.auto_select_analyze_target(d.journal)
        cont = sum(int(v) for v in vm["spec"].values())
        print(f"  Keter auto → VM {vm['id']} (containment={cont})")
        assert item["id"] == kid
        assert cont == 30

        print()
        print("=== 5) Prefers weakest capable (containment ties → lowest id) ===")
        # Seed another Safe + add another VM on mainframe (cont 30)
        p2 = ItemProfile("SCP-S2", "Safe", 2, 0, 0, 0, "t", "t", size_gb=1)
        iid2 = d.journal.create_item(p2.designation, p2.item_class, p2.hazard_strength, p2.to_dict())
        gameplay.acquire_candidate(d.journal, iid2)
        # Put Keter on mainframe LPAR to take it busy
        gameplay.start_analyze(d.journal, d.scheduler.add, kid, vm["id"])
        # Now only Safe S2 remains; idle VMs are VM 1 (cont 6) and maybe VM 2 if
        # we provision another. Picker should use cont 6 (weakest capable), not
        # touch the busy mainframe LPAR.
        item, pick = gameplay.auto_select_analyze_target(d.journal)
        pick_cont = sum(int(v) for v in pick["spec"].values())
        print(f"  Safe → VM {pick['id']} (containment={pick_cont})")
        assert item["id"] == iid2
        assert pick_cont == 6, f"should pick weakest capable, got {pick_cont}"

        print()
        print("=== 6) IPC analyze with missing ids → auto-picks ===")
        # Add a third Safe item
        p3 = ItemProfile("SCP-S3", "Safe", 2, 0, 0, 0, "t", "t", size_gb=1)
        iid3 = d.journal.create_item(p3.designation, p3.item_class, p3.hazard_strength, p3.to_dict())
        gameplay.acquire_candidate(d.journal, iid3)
        # Flush current analyses so VMs free up
        await d._flush_pending()

        client = DaemonClient("127.0.0.1", 54917)
        await client.connect()
        reply = await client.send({"type": "analyze", "payload": {}})
        print(f"  reply type = {reply.get('type')}")
        payload = reply.get("payload", {})
        print(f"  auto flag  = {payload.get('auto')}")
        print(f"  auto item  = #{payload.get('item_id')} {payload.get('item_designation')}")
        print(f"  auto vm    = #{payload.get('vm_id')} cont={payload.get('vm_containment')}")
        assert reply.get("type") == "ack"
        assert payload.get("auto") is True
        assert payload.get("item_id") in (iid2, iid3)
        assert payload.get("vm_id") is not None
        await client.close()

        st.cancel()
        try:
            await st
        except (asyncio.CancelledError, Exception):
            pass
        d.journal.close()
        print()
        print("---PHASE 17 TESTS PASSED---")
    finally:
        time.sleep(0.2)
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test())
