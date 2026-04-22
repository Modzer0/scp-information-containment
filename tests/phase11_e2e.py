import asyncio
import shutil
import tempfile
import time
from pathlib import Path

from scp.daemon import gameplay, procurement, sites, transport
from scp.daemon.content.items import ItemProfile, generate
from scp.daemon.main import Daemon


async def test():
    td = Path(tempfile.mkdtemp())
    try:
        d = Daemon(db_path=td / "p11.db", port=54900)
        gameplay.bootstrap_if_empty(d.journal)
        d.scheduler.rehydrate()
        await d.ipc.start()
        st = asyncio.create_task(d.scheduler.run())
        d.journal.set_funding(500_000_000)

        print("=== 1) procedural items persist size_gb in the DB ===")
        import random
        p = generate(random.Random(1))
        iid = d.journal.create_item(
            p.designation, p.item_class, p.hazard_strength, p.to_dict()
        )
        item = d.journal.get_item(iid)
        print(f"  generated={p.size_gb}  stored={item['size_gb']}")
        assert abs(item["size_gb"] - p.size_gb) < 0.01
        # Acquire should show storage climbing
        storage_before = procurement.site_utilization(d.journal, 1)["storage_used_gb"]
        gameplay.acquire_candidate(d.journal, iid)
        storage_after = procurement.site_utilization(d.journal, 1)["storage_used_gb"]
        delta = storage_after - storage_before
        print(f"  storage used rose by {delta:.2f} GB (expected ~{p.size_gb:.2f})")
        # site_utilization rounds storage/tape to 1 decimal — allow 0.1 slack
        assert abs(delta - p.size_gb) <= 0.15

        print()
        print("=== 2) archived items count in tape_used ===")
        d.journal.update_staff_skills(1, {"infosec": 90, "memetics": 50, "forensics": 20})
        d.journal.update_vm_spec(1, {
            "memory_encryption": 10, "isolation": 8, "mnestic_firmware": 4,
            "physical_shielding": 6, "scanner_freshness": 2,
        })
        d.journal.set_site_encryption(1, "type1")
        gameplay.start_analyze(d.journal, d.scheduler.add, iid, 1)
        await asyncio.sleep(0.5)
        tape_before = procurement.site_utilization(d.journal, 1)["tape_used_gb"]
        gameplay.start_archive(d.journal, d.scheduler.add, iid)
        await asyncio.sleep(0.5)
        tape_after = procurement.site_utilization(d.journal, 1)["tape_used_gb"]
        print(f"  tape used: {tape_before:.2f} -> {tape_after:.2f} GB")
        assert tape_after > tape_before
        assert abs(tape_after - p.size_gb) <= 0.15

        print()
        print("=== 3) range parsing (TUI) ===")
        from scp.tui.main import ScpTui
        app = ScpTui()
        assert app._parse_id_range("5") == [5]
        assert app._parse_id_range("3-7") == [3, 4, 5, 6, 7]
        assert app._parse_id_range("1,3,5") == [1, 3, 5]
        assert app._parse_id_range("1-3,7,10-12") == [1, 2, 3, 7, 10, 11, 12]
        assert app._parse_id_range("2-4,3-5") == [2, 3, 4, 5]    # dedup
        print("  PASS all range cases")

        print()
        print("=== 4) batch transfer: prepare 5 archived items ===")
        sites.on_site_established(d.journal, "office_closet", "Site-Bravo")
        site2 = next(s for s in d.journal.list_sites() if s["name"] == "Site-Bravo")
        d.journal.create_tape_library(
            site_id=site2["id"], sku="tape-lib-small", capacity_gb=500_000
        )
        archived_ids = []
        for i in range(5):
            pp = ItemProfile(f"SCP-B{i:03d}", "Safe", 2, 0, 0, 0, "t", "t", size_gb=3)
            xid = d.journal.create_item(
                pp.designation, pp.item_class, pp.hazard_strength, pp.to_dict()
            )
            gameplay.acquire_candidate(d.journal, xid)
            gameplay.start_analyze(d.journal, d.scheduler.add, xid, 1)
            await asyncio.sleep(0.15)
            gameplay.start_archive(d.journal, d.scheduler.add, xid)
            await asyncio.sleep(0.15)
            archived_ids.append(xid)
        archived = [
            d.journal.get_item(i) for i in archived_ids
        ]
        ready = [a for a in archived if a["state"] == "archived"]
        print(f"  archived {len(ready)}/{len(archived_ids)} at site 1")
        assert len(ready) == 5

        print()
        print("=== 5) batch transfer via IPC range ===")
        # Simulate what the TUI does: parse range, send one transfer per id
        ids_str = f"{archived_ids[0]}-{archived_ids[-1]}"
        parsed = app._parse_id_range(ids_str)
        print(f"  parsed {ids_str!r} -> {parsed}")
        ok = 0
        for iid in parsed:
            try:
                transport.transfer_item(
                    d.journal, d.scheduler.add, iid, site2["id"], "truck"
                )
                ok += 1
            except ValueError as e:
                print(f"    item {iid}: {e}")
        print(f"  batch: {ok}/{len(parsed)} transfers initiated")
        assert ok == 5

        st.cancel()
        try:
            await st
        except (asyncio.CancelledError, Exception):
            pass
        d.journal.close()
        print()
        print("---PHASE 11 TESTS PASSED---")
    finally:
        time.sleep(0.2)
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test())
