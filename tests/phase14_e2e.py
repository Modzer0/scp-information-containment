"""
Phase 14 — site security layer.

Covers:
- base rating per site type
- equipment install + rating bonus aggregation
- site-type gating (tent rejects blast-doors; subsea_pod rejects fence)
- guard contracts hooked into the contracts system
- incident chance curve (50% at rating 0, 0% at 50+)
- theft → item.state='stolen'
- sabotage_power → outage row created
- sabotage_host → clean host flipped to 'suspect'
- degradation: sabotage_host with no clean hosts = attempted_breach
- on_roll sweep doesn't crash; triggers incidents on low-rated sites
"""
import asyncio
import random
import shutil
import tempfile
import time
from pathlib import Path

from scp.daemon import contracts, gameplay, security, sites
from scp.daemon.content.items import ItemProfile
from scp.daemon.main import Daemon


async def test():
    td = Path(tempfile.mkdtemp())
    try:
        d = Daemon(db_path=td / "p14.db", port=54914)
        gameplay.bootstrap_if_empty(d.journal)
        d.scheduler.rehydrate()
        await d.ipc.start()
        st = asyncio.create_task(d.scheduler.run())
        d.journal.set_funding(500_000_000)

        print("=== 1) base ratings per site type ===")
        info1 = security.compute_rating(d.journal, 1)
        print(f"  site 1 ({info1['site_type']}): base={info1['base']}")
        assert info1["base"] == 25  # onprem_dc

        sites.on_site_established(d.journal, "tent", "FOB-Tango")
        sites.on_site_established(d.journal, "subsea_pod", "Abyssal-One")
        sites.on_site_established(d.journal, "underground", "DeepVault")
        tent = next(s for s in d.journal.list_sites() if s["name"] == "FOB-Tango")
        pod = next(s for s in d.journal.list_sites() if s["name"] == "Abyssal-One")
        bunker = next(s for s in d.journal.list_sites() if s["name"] == "DeepVault")
        assert security.compute_rating(d.journal, tent["id"])["base"] == 5
        assert security.compute_rating(d.journal, pod["id"])["base"] == 80
        assert security.compute_rating(d.journal, bunker["id"])["base"] == 70
        print(f"  tent=5  pod=80  underground=70  OK")

        print()
        print("=== 2) equipment install + rating bonus sums ===")
        security.install_equipment(d.journal, 1, "cctv-network")       # +5
        security.install_equipment(d.journal, 1, "motion-sensors")     # +6
        security.install_equipment(d.journal, 1, "access-control-system")  # +8
        info2 = security.compute_rating(d.journal, 1)
        assert info2["equipment_bonus"] == 19
        assert info2["total"] == 44
        print(f"  site 1 after 3 items: eq=+19  total=44  OK")

        print()
        print("=== 3) site-type gating on install ===")
        try:
            security.install_equipment(d.journal, pod["id"], "perimeter-fence")
            assert False, "should reject perimeter-fence on subsea_pod"
        except ValueError as e:
            print(f"  fence→pod rejected: {e}")
        try:
            security.install_equipment(d.journal, tent["id"], "blast-doors")
            assert False, "should reject blast-doors on tent"
        except ValueError as e:
            print(f"  blast-doors→tent rejected: {e}")
        try:
            security.install_equipment(d.journal, 1, "bogus-sku")
            assert False, "should reject unknown sku"
        except ValueError as e:
            print(f"  unknown sku rejected: {e}")

        print()
        print("=== 4) hire_guards via contracts system ===")
        contracts.subscribe(d.journal, d.scheduler.add,
                            type_id="pmsc_team_light", target_site_id=1)
        info3 = security.compute_rating(d.journal, 1)
        assert info3["guard_bonus"] == 15
        assert info3["total"] == 44 + 15
        print(f"  PMSC light on site 1: guards=+15  total={info3['total']}  OK")

        # Duplicate guard contract on same site → reject
        try:
            contracts.subscribe(d.journal, d.scheduler.add,
                                type_id="pmsc_team_light", target_site_id=1)
            assert False, "duplicate guard contract should reject"
        except ValueError as e:
            print(f"  duplicate guard contract rejected: {e}")

        # Stack an MTF squad on top
        contracts.subscribe(d.journal, d.scheduler.add,
                            type_id="mtf_squad", target_site_id=1)
        info4 = security.compute_rating(d.journal, 1)
        assert info4["guard_bonus"] == 15 + 40
        print(f"  + MTF squad: guards=+{info4['guard_bonus']}  total={info4['total']}")

        print()
        print("=== 5) incident chance curve ===")
        assert security._incident_chance(0) == 0.50
        assert security._incident_chance(10) == 0.40
        assert security._incident_chance(25) == 0.25
        assert security._incident_chance(50) == 0.0
        assert security._incident_chance(99) == 0.0
        print(f"  0→50%  10→40%  25→25%  50→0%  99→0%  OK")

        print()
        print("=== 6) theft turns a stolen archived SCP ===")
        p = ItemProfile("SCP-THF", "Safe", 2, 1, 0, 0, "t", "t", size_gb=1)
        iid = d.journal.create_item(p.designation, p.item_class, p.hazard_strength, p.to_dict())
        d.journal.set_item_state(iid, "archived")
        d.journal.set_item_site(iid, tent["id"])
        info_t = security.compute_rating(d.journal, tent["id"])
        r_theft = security._apply_incident(
            d.journal, tent["id"], info_t, "theft", random.Random(0)
        )
        assert r_theft["outcome"] == "item_stolen"
        item = d.journal.get_item(iid)
        assert item["state"] == "stolen"
        print(f"  item {iid} state after theft: {item['state']}  OK")

        print()
        print("=== 7) sabotage_power creates outage row ===")
        r_p = security._apply_incident(
            d.journal, tent["id"], info_t, "sabotage_power", random.Random(1)
        )
        assert r_p["outcome"] == "power_outage_2h"
        outs = d.journal.active_outages(tent["id"])
        assert any(o["kind"] == "sabotage" for o in outs)
        print(f"  {len(outs)} active outage(s) at tent (sabotage kind present)  OK")

        print()
        print("=== 8) sabotage_host flips clean → suspect; degrades when none ===")
        host_id = d.journal.create_host(
            site_id=tent["id"], name="host-T1", host_class="server",
            specs={"ram_gb": 128, "storage_gb": 4000, "power_w": 500},
            status="clean",
        )
        r_h = security._apply_incident(
            d.journal, tent["id"], info_t, "sabotage_host", random.Random(2)
        )
        assert r_h["outcome"] == "host_suspect"
        assert d.journal.get_host(host_id)["status"] == "suspect"
        print(f"  host {host_id} status after: suspect  OK")

        # Degradation: no clean hosts left
        r_h2 = security._apply_incident(
            d.journal, tent["id"], info_t, "sabotage_host", random.Random(3)
        )
        assert r_h2["kind"] == "attempted_breach"
        assert r_h2["outcome"] == "deterred"
        print(f"  2nd sabotage (no clean hosts): {r_h2['kind']}/{r_h2['outcome']}  OK")

        print()
        print("=== 9) on_roll sweep produces incidents on low-rated sites ===")
        rng2 = random.Random(7)
        total = 0
        kinds = []
        for _ in range(30):
            res = security.on_roll(d.journal, d.scheduler.add, rng2)
            for ev in res["triggered"]:
                total += 1
                kinds.append(ev["kind"])
        assert total > 0, "low-rated sites should roll incidents"
        print(f"  30 rolls → {total} incidents (kinds: {set(kinds)})")

        st.cancel()
        try:
            await st
        except (asyncio.CancelledError, Exception):
            pass
        d.journal.close()
        print()
        print("---PHASE 14 TESTS PASSED---")
    finally:
        time.sleep(0.2)
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test())
