from __future__ import annotations

import os
from datetime import timedelta
from typing import Any

from .clock import now_utc
from .journal import Journal
from .mistakes import CLEARANCE_REQUIRED, SKILL_RECOMMENDED


_TS = float(os.environ.get("SCP_TIME_SCALE", "1.0"))
# Default cadence: every 2 real-clock minutes (scaled). Small enough to feel
# responsive, large enough that agents don't spam actions faster than items
# can be processed.
AGENT_TICK_PERIOD_S = _TS * 120


def schedule_next_tick(schedule_fn: Any) -> None:
    eta = now_utc() + timedelta(seconds=AGENT_TICK_PERIOD_S)
    schedule_fn(eta, "staff_agent_tick", {})


# ---- eligibility helpers --------------------------------------------


def _can_handle_class(staff: dict, item_class: str) -> bool:
    required_clearance = CLEARANCE_REQUIRED.get(item_class, 0)
    required_infosec = SKILL_RECOMMENDED.get(item_class, 0)
    clearance = int(staff.get("clearance", 0))
    infosec = int(staff.get("skills", {}).get("infosec", 0))
    return clearance >= required_clearance and infosec >= required_infosec


def _item_site_match(item: dict, site_id: int | None) -> bool:
    cs = item.get("current_site_id")
    if cs is None:
        return True   # unassigned candidates are visible to all staff
    return int(cs) == int(site_id) if site_id is not None else False


# ---- per-staff action planning --------------------------------------


def _try_wipe_at_site(journal, schedule_fn, staff, site_id):
    """If there's an infected host at the staff's site and they have
    forensics skill, start a wipe."""
    from . import gameplay
    if int(staff.get("skills", {}).get("forensics", 0)) < 15:
        return None
    hosts = [
        h for h in journal.list_hosts()
        if h.get("site_id") == site_id and h.get("status") == "infected"
    ]
    # Don't double-wipe: skip if a wipe is already scheduled for this host
    pending_wipes = {
        int(p["payload"].get("host_id", -1))
        for p in journal.pending()
        if p["kind"] == "wipe_complete"
    }
    for h in hosts:
        if h["id"] in pending_wipes:
            continue
        try:
            gameplay.start_wipe(
                journal, schedule_fn, h["id"], operator_id=staff["id"]
            )
            return {"action": "wipe", "host_id": h["id"]}
        except ValueError:
            continue
    return None


def _try_archive(journal, schedule_fn, staff, site_id):
    """Archive analyzed items at the staff's site (max revenue priority)."""
    from . import gameplay
    analyzed = [
        i for i in journal.list_items("analyzed")
        if i.get("current_site_id") == site_id
    ]
    for item in analyzed:
        if not _can_handle_class(staff, item["class"]):
            continue
        try:
            gameplay.start_archive(
                journal, schedule_fn, item["id"], operator_id=staff["id"]
            )
            return {"action": "archive", "item_id": item["id"]}
        except ValueError:
            continue
    return None


def _try_analyze(journal, schedule_fn, staff, site_id):
    """Analyze a quarantined item on an idle VM the staff can handle."""
    from . import gameplay
    from .containment import VmSpec
    quarantined = [
        i for i in journal.list_items("quarantined")
        if i.get("current_site_id") == site_id
    ]
    if not quarantined:
        return None
    # VMs on the same site, clean host, idle
    all_vms = journal.list_vms()
    site_host_ids = {
        h["id"] for h in journal.list_hosts() if h.get("site_id") == site_id
    }
    idle_vms = [
        v for v in all_vms
        if v.get("host_id") in site_host_ids
        and v.get("status") == "idle"
        and v.get("host_status") == "clean"
    ]
    for item in quarantined:
        if not _can_handle_class(staff, item["class"]):
            continue
        hazard = int(item["hazard_strength"])
        for vm in idle_vms:
            spec = VmSpec.from_dict(vm["spec"])
            # Agent only analyzes when containment is fully safe (delta <= 0).
            # Leaves soft-rail / risky plays to human judgement.
            if spec.containment < hazard:
                continue
            try:
                result = gameplay.start_analyze(
                    journal, schedule_fn, item["id"], vm["id"],
                    operator_id=staff["id"],
                )
                if result.get("blocked"):
                    # Any mistake detected → skip rather than override.
                    continue
                return {
                    "action": "analyze",
                    "item_id": item["id"],
                    "vm_id": vm["id"],
                }
            except ValueError:
                continue
    return None


def _try_acquire(journal, schedule_fn, staff, site_id):
    """Acquire a candidate within clearance. Uses staff's assigned site."""
    from . import gameplay
    candidates = journal.list_items("candidate")
    for item in candidates:
        required_clearance = CLEARANCE_REQUIRED.get(item["class"], 1)
        if int(staff.get("clearance", 0)) < required_clearance:
            continue
        try:
            gameplay.acquire_candidate(
                journal, item["id"],
                operator_id=staff["id"],
                target_site_id=site_id,
            )
            return {"action": "acquire", "item_id": item["id"]}
        except ValueError:
            continue
    return None


def _try_scan(journal, schedule_fn, staff):
    """Start a scan if no active scan exists and candidate pool is thin."""
    from . import gameplay
    has_scan = any(
        p["kind"] == "scan_complete" for p in journal.pending()
    )
    if has_scan:
        return None
    candidate_count = len(journal.list_items("candidate"))
    if candidate_count >= 3:
        return None   # queue is healthy
    try:
        gameplay.start_scan(journal, schedule_fn, operator_id=staff["id"])
        return {"action": "scan"}
    except ValueError:
        return None


# ---- tick entry point -----------------------------------------------


def on_tick(journal: Journal, schedule_fn: Any) -> dict:
    """One agent pass: each autonomous staff member takes at most one
    action in priority order. Schedules next tick regardless."""
    actions: list[dict] = []
    roster = journal.list_staff()

    # Two-pass: first do reactive work (wipes + archives), then initiating
    # work (analyze + acquire + scan). This prevents a single staff from
    # blocking cleanup by analyzing first when there's an infected host.
    for phase in ("reactive", "initiate"):
        for staff in roster:
            if staff.get("autonomy") != "on":
                continue
            if staff.get("status") != "active":
                continue
            site_id = staff.get("assigned_site_id")
            if site_id is None:
                continue

            if phase == "reactive":
                for fn in (_try_wipe_at_site, _try_archive):
                    result = fn(journal, schedule_fn, staff, site_id)
                    if result:
                        result.update(
                            {"staff_id": staff["id"], "staff_name": staff["name"]}
                        )
                        journal.append("agent_action", "INFO", result)
                        actions.append(result)
                        break
            else:
                for fn in (_try_analyze, _try_acquire):
                    result = fn(journal, schedule_fn, staff, site_id)
                    if result:
                        result.update(
                            {"staff_id": staff["id"], "staff_name": staff["name"]}
                        )
                        journal.append("agent_action", "INFO", result)
                        actions.append(result)
                        break
                else:
                    # Only try scan if nothing else fit
                    result = _try_scan(journal, schedule_fn, staff)
                    if result:
                        result.update(
                            {"staff_id": staff["id"], "staff_name": staff["name"]}
                        )
                        journal.append("agent_action", "INFO", result)
                        actions.append(result)

    schedule_next_tick(schedule_fn)
    return {"actions": actions, "count": len(actions)}
