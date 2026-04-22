import asyncio
import shutil
import tempfile
import time
from pathlib import Path

from scp.daemon import gameplay, sites
from scp.daemon.content.items import ItemProfile
from scp.daemon.main import Daemon


async def test():
    td = Path(tempfile.mkdtemp())
    try:
        d = Daemon(db_path=td / "p8.db", port=54300)
        gameplay.bootstrap_if_empty(d.journal)
        d.scheduler.rehydrate()
        await d.ipc.start()
        st = asyncio.create_task(d.scheduler.run())
        d.journal.set_funding(500_000_000)

        # Skilled operator + well-contained VM so analysis is stable
        d.journal.update_staff_skills(1, {"infosec": 90, "memetics": 50, "forensics": 20})
        d.journal.update_vm_spec(1, {
            "memory_encryption": 10, "isolation": 8, "mnestic_firmware": 4,
            "physical_shielding": 6, "scanner_freshness": 2,
        })
        d.journal.set_site_encryption(1, "type1")

        print("=== 1) same-site archive uses base duration ===")
        p = ItemProfile("SCP-8001", "Safe", 3, 1, 0, 0, "t", "t", size_gb=5)
        iid = d.journal.create_item(
            p.designation, p.item_class, p.hazard_strength, p.to_dict()
        )
        d.journal.set_item_size(iid, 5)
        gameplay.acquire_candidate(d.journal, iid)
        gameplay.start_analyze(d.journal, d.scheduler.add, iid, 1)
        await asyncio.sleep(0.3)
        r = gameplay.start_archive(d.journal, d.scheduler.add, iid)
        print(f"  same-site: source={r['source_site_id']} target={r['target_site_id']} size={r['size_gb']} GB")
        assert r["source_site_id"] == r["target_site_id"]
        await asyncio.sleep(0.3)
        item = d.journal.get_item(iid)
        print(f"  final state: {item['state']} @site {item['current_site_id']}")
        assert item["state"] == "archived"

        print()
        print("=== 2) cross-site archive adds transmission time ===")
        sites.on_site_established(d.journal, "office_closet", "Site-Far")
        site2 = next(s for s in d.journal.list_sites() if s["name"] == "Site-Far")

        # Site-Far needs a tape library or archives will route back to site 1
        d.journal.create_tape_library(
            site_id=site2["id"], sku="tape-lib-small", capacity_gb=500_000
        )
        # Slow the destination link so transmission dominates
        d.journal.set_site_network(site2["id"], "geo_sat")  # 30 Mbps

        # Two fresh items so we can compare durations without races
        def _prep(des: str, size: float) -> int:
            pp = ItemProfile(des, "Euclid", 8, 3, 2, 1, "t", "t", size_gb=size)
            i = d.journal.create_item(
                pp.designation, pp.item_class, pp.hazard_strength, pp.to_dict()
            )
            d.journal.set_item_size(i, size)
            gameplay.acquire_candidate(d.journal, i)
            return i

        iid_a = _prep("SCP-8002A", 200)
        iid_b = _prep("SCP-8002B", 200)
        gameplay.start_analyze(d.journal, d.scheduler.add, iid_a, 1)
        await asyncio.sleep(0.3)
        gameplay.start_analyze(d.journal, d.scheduler.add, iid_b, 1)
        await asyncio.sleep(0.3)

        same_r = gameplay.start_archive(d.journal, d.scheduler.add, iid_a)
        cross_r = gameplay.start_archive(
            d.journal, d.scheduler.add, iid_b, target_site_id=site2["id"]
        )
        from datetime import datetime
        same_dt = datetime.fromisoformat(same_r["eta"])
        cross_dt = datetime.fromisoformat(cross_r["eta"])
        print(f"  same-site ETA:  {same_r['eta']}")
        print(f"  cross-site ETA: {cross_r['eta']}")
        assert cross_dt > same_dt, "cross-site should take longer than same-site"
        print("  PASS: cross-site is slower")

        await asyncio.sleep(6.0)   # GEO-sat transmission at compressed scale
        item_a = d.journal.get_item(iid_a)
        item_b = d.journal.get_item(iid_b)
        print(f"  item A (same-site):  state={item_a['state']} @site {item_a['current_site_id']}")
        print(f"  item B (cross-site): state={item_b['state']} @site {item_b['current_site_id']}")
        assert item_a["state"] == "archived"
        assert item_a["current_site_id"] == 1
        assert item_b["state"] == "archived"
        assert item_b["current_site_id"] == site2["id"]

        print()
        print("=== 3) archived items retain size + site metadata ===")
        archived = d.journal.list_items("archived")
        print(f"  archived count: {len(archived)}")
        for a in archived:
            print(
                f"    {a['designation']:10s} {a['class']:6s} "
                f"{a['size_gb']:6.1f} GB @site {a['current_site_id']}  "
                f"enc_at_rest={a['encrypted_at_rest']}"
            )
        assert len(archived) >= 2

        print()
        print("=== 4) refusal when target_site_id invalid ===")
        p3 = ItemProfile("SCP-8003", "Safe", 2, 0, 0, 0, "t", "t", size_gb=3)
        iid3 = d.journal.create_item(
            p3.designation, p3.item_class, p3.hazard_strength, p3.to_dict()
        )
        d.journal.set_item_size(iid3, 3)
        gameplay.acquire_candidate(d.journal, iid3)
        gameplay.start_analyze(d.journal, d.scheduler.add, iid3, 1)
        await asyncio.sleep(0.3)
        try:
            gameplay.start_archive(d.journal, d.scheduler.add, iid3,
                                   target_site_id=999)
            assert False
        except ValueError as e:
            print(f"  PASS: {e}")

        st.cancel()
        try:
            await st
        except (asyncio.CancelledError, Exception):
            pass
        d.journal.close()
        print()
        print("---PHASE 8 TESTS PASSED---")
    finally:
        time.sleep(0.2)
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test())
