import asyncio
import shutil
import tempfile
import time
from pathlib import Path

from scp.daemon import agents, gameplay
from scp.daemon.content.items import ItemProfile
from scp.daemon.main import Daemon


async def test():
    td = Path(tempfile.mkdtemp())
    try:
        d = Daemon(db_path=td / "p10.db", port=54600)
        gameplay.bootstrap_if_empty(d.journal)
        d.scheduler.rehydrate()
        await d.ipc.start()
        st = asyncio.create_task(d.scheduler.run())
        d.journal.set_funding(5_000_000)

        print("=== 1) autonomy defaults to off ===")
        roster = d.journal.list_staff()
        for s in roster:
            assert s["autonomy"] == "off"
        print(f"  PASS: all {len(roster)} bootstrap staff start off")

        print()
        print("=== 2) set autonomy on a player-avatar ===")
        d.journal.set_staff_autonomy(1, "on")
        staff = d.journal.get_staff(1)
        assert staff["autonomy"] == "on"
        print(f"  {staff['name']} autonomy = {staff['autonomy']}")

        print()
        print("=== 3) agent tick with no work → no actions ===")
        result = agents.on_tick(d.journal, d.scheduler.add)
        print(f"  count: {result['count']}")
        # With empty queue + no candidates, agent should start a scan
        assert any(a["action"] == "scan" for a in result["actions"])

        print()
        print("=== 4) agent acquires candidates within clearance ===")
        # Seed a Safe candidate manually; player is L3
        p = ItemProfile("SCP-A001", "Safe", 3, 1, 0, 0, "t", "t", size_gb=5)
        iid = d.journal.create_item(
            p.designation, p.item_class, p.hazard_strength, p.to_dict()
        )
        d.journal.set_item_size(iid, 5)
        # Cancel the scan so the agent focuses on acquire
        # (actually the agent will still acquire candidates first since
        # priority is acquire → analyze → scan; but there's a pending scan
        # blocking new scans. Let's run another tick)
        result = agents.on_tick(d.journal, d.scheduler.add)
        print(f"  actions: {[a['action'] for a in result['actions']]}")
        item = d.journal.get_item(iid)
        print(f"  item state: {item['state']}")
        assert item["state"] == "quarantined"

        print()
        print("=== 5) agent analyzes quarantined items when VM is safe ===")
        # Upgrade VM containment so it can handle Safe items (hazard 3)
        d.journal.update_vm_spec(1, {
            "memory_encryption": 10, "isolation": 8, "mnestic_firmware": 4,
            "physical_shielding": 6, "scanner_freshness": 2,
        })
        d.journal.set_site_encryption(1, "type1")
        # Player already L3, infosec 30 (meets Safe requirement)
        result = agents.on_tick(d.journal, d.scheduler.add)
        print(f"  actions: {[a['action'] for a in result['actions']]}")
        # Should have analyzed
        item = d.journal.get_item(iid)
        print(f"  item state: {item['state']}")
        assert item["state"] in ("analyzing", "analyzed")

        # Let analysis complete
        await asyncio.sleep(0.5)

        print()
        print("=== 6) agent archives analyzed items ===")
        result = agents.on_tick(d.journal, d.scheduler.add)
        print(f"  actions: {[a['action'] for a in result['actions']]}")
        await asyncio.sleep(0.5)
        item = d.journal.get_item(iid)
        print(f"  item state: {item['state']}")
        assert item["state"] in ("archiving", "archived")

        print()
        print("=== 7) clearance gate: L1 staff skips Keter ===")
        # Turn off player, turn on Tech Osei (L1, low infosec)
        d.journal.set_staff_autonomy(1, "off")
        d.journal.set_staff_autonomy(3, "on")
        osei = d.journal.get_staff(3)
        print(f"  Tech Osei: clearance L{osei['clearance']}  infosec={osei['skills'].get('infosec', 0)}")
        # Seed a Keter candidate
        p_k = ItemProfile("SCP-K001", "Keter", 18, 7, 7, 7, "t", "t", size_gb=2000)
        k_iid = d.journal.create_item(
            p_k.designation, p_k.item_class, p_k.hazard_strength, p_k.to_dict()
        )
        d.journal.set_item_size(k_iid, 2000)
        result = agents.on_tick(d.journal, d.scheduler.add)
        keter_item = d.journal.get_item(k_iid)
        # Keter needs clearance 3; Osei is 1 → should NOT acquire
        print(f"  Keter item state: {keter_item['state']}")
        assert keter_item["state"] == "candidate"
        print("  PASS: Osei correctly refused to acquire Keter")

        print()
        print("=== 8) agent wipes infected host (forensics skill) ===")
        # Infect the host, Tech Osei has forensics=30 → should wipe
        d.journal.set_host_status(1, "infected")
        result = agents.on_tick(d.journal, d.scheduler.add)
        print(f"  actions: {[a['action'] for a in result['actions']]}")
        pending = d.journal.pending()
        has_wipe = any(p["kind"] == "wipe_complete" for p in pending)
        print(f"  wipe queued: {has_wipe}")
        assert has_wipe
        print("  PASS: autonomous wipe initiated")

        print()
        print("=== 9) set_autonomy IPC verb ===")
        import json
        reader, writer = await asyncio.open_connection("127.0.0.1", 54600)
        writer.write(b'{"type":"set_autonomy","payload":{"staff_id":2,"mode":"on"}}\n')
        await writer.drain()
        reply = json.loads((await reader.readline()).decode())
        print(f"  reply: {reply}")
        assert reply["type"] == "ack"
        vey = d.journal.get_staff(2)
        assert vey["autonomy"] == "on"
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

        st.cancel()
        try:
            await st
        except (asyncio.CancelledError, Exception):
            pass
        d.journal.close()
        print()
        print("---PHASE 10 TESTS PASSED---")
    finally:
        time.sleep(0.2)
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test())
