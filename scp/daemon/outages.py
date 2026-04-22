from __future__ import annotations

import os
import random
from datetime import timedelta
from typing import Any

from .clock import iso, now_utc
from .journal import Journal


_TS = float(os.environ.get("SCP_TIME_SCALE", "1.0"))


def _d(seconds: float) -> float:
    return seconds * _TS


# Civilian-infrastructure failure probability per roll (per site per day).
# Tuned to produce an occasional event during long runs — grid outages
# are real but rare. Higher on rural sites would be realistic; this MVP
# is uniform.
GRID_OUTAGE_PROB_PER_DAY = 0.02      # ~1 in 50 days
GRID_OUTAGE_DURATION_H = (1.0, 12.0) # 1–12h outage

# Rolled once per real-clock period (scaled). Default every 24 in-game hours.
OUTAGE_ROLL_PERIOD_S = _d(24 * 3600)


def schedule_next_roll(schedule_fn: Any) -> None:
    eta = now_utc() + timedelta(seconds=OUTAGE_ROLL_PERIOD_S)
    schedule_fn(eta, "outage_roll", {})


def on_roll(
    journal: Journal,
    schedule_fn: Any,
    rng: random.Random,
) -> dict:
    """Roll outage probabilities once per scheduled period for every site
    that depends on civilian grid power. Sites with an active outage are
    skipped. Returns a summary of triggered outages."""
    from . import sites as site_catalog
    from . import procurement

    triggered: list[dict] = []
    for s in journal.list_sites():
        # Diesel-required sites (field / mobidc) don't rely on grid,
        # so grid outage doesn't apply. (Their analog is fuel delivery.)
        if site_catalog.site_requires_diesel(journal, s["id"]):
            continue
        if journal.active_outages(s["id"]):
            continue
        if rng.random() > GRID_OUTAGE_PROB_PER_DAY:
            continue
        duration = rng.uniform(*GRID_OUTAGE_DURATION_H)
        # Resilience check: battery + fuel hours at current draw
        util = procurement.site_utilization(journal, s["id"])
        ride = float(util.get("ride_through_hours", 0.0))
        ride_through = ride >= duration
        eta_end = now_utc() + timedelta(seconds=_d(duration * 3600))
        outage_id = journal.create_outage(
            site_id=s["id"],
            kind="grid_power",
            duration_h=duration,
            ride_through=ride_through,
            eta_end_utc=eta_end,
        )
        schedule_fn(eta_end, "outage_end", {"outage_id": outage_id})
        sev = "NOTICE" if ride_through else "ALERT"
        journal.append(
            "grid_outage_started",
            sev,
            {
                "outage_id": outage_id,
                "site_id": s["id"],
                "duration_h": round(duration, 2),
                "ride_through": ride_through,
                "resilience_hours": round(ride, 2),
            },
        )
        triggered.append({
            "outage_id": outage_id,
            "site_id": s["id"],
            "duration_h": round(duration, 2),
            "ride_through": ride_through,
        })
    # Schedule the next roll regardless
    schedule_next_roll(schedule_fn)
    return {"triggered": triggered}


def on_outage_end(journal: Journal, outage_id: int) -> dict:
    journal.resolve_outage(outage_id)
    journal.append(
        "grid_outage_resolved",
        "INFO",
        {"outage_id": outage_id},
    )
    return {"outage_id": outage_id, "status": "resolved"}


def trigger_manual_outage(
    journal: Journal,
    schedule_fn: Any,
    site_id: int,
    duration_h: float = 4.0,
) -> dict:
    """Admin/debug: force an outage at a site for testing."""
    from . import procurement
    util = procurement.site_utilization(journal, site_id)
    ride = float(util.get("ride_through_hours", 0.0))
    ride_through = ride >= duration_h
    eta_end = now_utc() + timedelta(seconds=_d(duration_h * 3600))
    outage_id = journal.create_outage(
        site_id=site_id,
        kind="grid_power",
        duration_h=duration_h,
        ride_through=ride_through,
        eta_end_utc=eta_end,
    )
    schedule_fn(eta_end, "outage_end", {"outage_id": outage_id})
    sev = "NOTICE" if ride_through else "ALERT"
    journal.append(
        "grid_outage_started",
        sev,
        {
            "outage_id": outage_id,
            "site_id": site_id,
            "duration_h": duration_h,
            "ride_through": ride_through,
            "resilience_hours": round(ride, 2),
            "manual": True,
        },
    )
    return {
        "outage_id": outage_id,
        "site_id": site_id,
        "duration_h": duration_h,
        "ride_through": ride_through,
    }
