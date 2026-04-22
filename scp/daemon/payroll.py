from __future__ import annotations

import os
from datetime import timedelta
from typing import Any

from .clock import iso, now_utc
from .journal import Journal


_TS = float(os.environ.get("SCP_TIME_SCALE", "1.0"))
PAYROLL_PERIOD_S = _TS * 7 * 86_400   # weekly (real-clock, scaled)


def schedule_next_payroll(schedule_fn: Any) -> None:
    eta = now_utc() + timedelta(seconds=PAYROLL_PERIOD_S)
    schedule_fn(eta, "payroll_run", {})


def on_payroll_run(journal: Journal, schedule_fn: Any) -> dict:
    """Sum weekly wages across all non-player staff and deduct from funding.
    Player-avatar salary is 0 (no explicit wage for yourself)."""
    roster = journal.list_staff()
    weekly_total = 0
    details: list[dict] = []
    for s in roster:
        if s.get("is_player"):
            continue
        annual = int(s.get("salary", 0) or 0)
        weekly = annual // 52
        if weekly == 0:
            continue
        weekly_total += weekly
        details.append({"staff_id": s["id"], "name": s["name"], "weekly": weekly})

    balance_before = journal.get_funding()
    balance_after = journal.adjust_funding(-weekly_total)
    shortfall = balance_after < 0

    result = {
        "weekly_total": weekly_total,
        "balance_before": balance_before,
        "balance_after": balance_after,
        "staff_paid": len(details),
        "shortfall": shortfall,
    }
    severity = "ALERT" if shortfall else "INFO"
    journal.append(
        "payroll_run",
        severity,
        {**result, "details": details[:20]},
    )
    schedule_next_payroll(schedule_fn)
    return result
