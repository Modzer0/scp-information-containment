"""
Phase 12 — data-link archive transmission.

Covers:
- `transport_methods` includes `data_link`
- encryption gate enforced per item class (Safe/Euclid/Keter)
- bandwidth-scaled duration
- destination tape-capacity check
- cost = $500 base + $100/GB
- successful transit lands the item at the destination site
"""
import asyncio
import shutil
import tempfile
import time
from pathlib import Path

from scp.daemon import gameplay, sites, transport
from scp.daemon.content.items import ItemProfile
from scp.daemon.main import Daemon


async def _prep_archived(d, designation, klass, strength, size_gb):
    p = ItemProfile(designation, klass, strength, 1, 0, 0, "t", "t", size_gb=size_gb)
    iid = d.journal.create_item(p.designation, p.item_class, p.hazard_strength, p.to_dict())
    gameplay.acquire_candidate(d.journal, iid)
    gameplay.start_analyze(d.journal, d.scheduler.add, iid, 1)
    await asyncio.sleep(0.3)
    gameplay.start_archive(d.journal, d.scheduler.add, iid)
    await asyncio.sleep(0.5)
    return iid


async def test():
    td = Path(tempfile.mkdtemp())
    try:
        d = Daemon(db_path=td / "p12.db", port=54912)
        gameplay.bootstrap_if_empty(d.journal)
        d.scheduler.rehydrate()
        await d.ipc.start()
        st = asyncio.create_task(d.scheduler.run())
        d.journal.set_funding(500_000_000)

        # analyst + VM → clean archive
        d.journal.update_staff_skills(1, {"infosec": 90, "memetics": 50, "forensics": 20})
        d.journal.update_vm_spec(1, {
            "memory_encryption": 10, "isolation": 8, "mnestic_firmware": 4,
            "physical_shielding": 6, "scanner_freshness": 2,
        })

        # build site B with tape
        sites.on_site_established(d.journal, "office_closet", "Site-DL2")
        site2 = next(s for s in d.journal.list_sites() if s["name"] == "Site-DL2")
        d.journal.create_tape_library(
            site_id=site2["id"], sku="tape-lib-small", capacity_gb=500_000
        )

        print("=== 1) transport_methods includes data_link ===")
        methods = transport.list_methods()
        ids = [m.method_id for m in methods]
        print(f"  methods: {ids}")
        assert "data_link" in ids

        print()
        print("=== 2) Safe item transfers over software encryption ===")
        d.journal.set_site_encryption(1, "software")
        d.journal.set_site_encryption(site2["id"], "software")
        iid = await _prep_archived(d, "SCP-DL-001", "Safe", 3, 4)
        r = transport.transfer_item(d.journal, d.scheduler.add, iid, site2["id"], "data_link")
        print(f"  cost=${r['cost']}  bandwidth={r['bandwidth_mbps']}Mbps  t={r['transmission_s_unscaled']}s")
        # base $500 + 4 GB * $100/GB = $900
        assert r["cost"] == 900, f"unexpected cost ${r['cost']}"
        assert r["bandwidth_mbps"] == 200   # office_closet dsl @ 200 Mbps
        assert r["transmission_s_unscaled"] > 0
        await asyncio.sleep(1.5)
        item = d.journal.get_item(iid)
        print(f"  final: state={item['state']} @site {item['current_site_id']}")
        assert item["state"] == "archived"
        assert item["current_site_id"] == site2["id"]

        print()
        print("=== 3) Keter rejected on software; allowed on type1 ===")
        iid_k = await _prep_archived(d, "SCP-DL-002", "Keter", 9, 5)
        try:
            transport.transfer_item(d.journal, d.scheduler.add, iid_k, site2["id"], "data_link")
            assert False, "Keter should have been rejected on software"
        except ValueError as e:
            print(f"  REJECTED (expected): {e}")
        d.journal.set_site_encryption(1, "type1")
        d.journal.set_site_encryption(site2["id"], "type1")
        r_k = transport.transfer_item(d.journal, d.scheduler.add, iid_k, site2["id"], "data_link")
        print(f"  Keter on type1: cost=${r_k['cost']}  t={r_k['transmission_s_unscaled']}s")
        assert r_k["cost"] == 1000   # $500 + 5 GB × $100

        print()
        print("=== 4) unencrypted source rejected ===")
        d.journal.set_site_encryption(1, "none")
        iid_n = await _prep_archived(d, "SCP-DL-003", "Safe", 2, 2)
        try:
            transport.transfer_item(d.journal, d.scheduler.add, iid_n, site2["id"], "data_link")
            assert False, "unencrypted source should reject"
        except ValueError as e:
            print(f"  REJECTED (expected): {e}")

        print()
        print("=== 5) tape-full destination rejected ===")
        d.journal.set_site_encryption(1, "type1")
        sites.on_site_established(d.journal, "tent", "Site-Tiny")
        site3 = next(s for s in d.journal.list_sites() if s["name"] == "Site-Tiny")
        d.journal.create_tape_library(
            site_id=site3["id"], sku="tape-lib-small", capacity_gb=1
        )
        d.journal.set_site_encryption(site3["id"], "type1")
        iid_big = await _prep_archived(d, "SCP-DL-BIG", "Safe", 2, 5)
        try:
            transport.transfer_item(d.journal, d.scheduler.add, iid_big, site3["id"], "data_link")
            assert False, "tape-full dest should reject"
        except ValueError as e:
            print(f"  REJECTED (expected): {e}")

        st.cancel()
        try:
            await st
        except (asyncio.CancelledError, Exception):
            pass
        d.journal.close()
        print()
        print("---PHASE 12 TESTS PASSED---")
    finally:
        time.sleep(0.2)
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test())
