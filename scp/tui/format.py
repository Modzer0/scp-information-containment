from __future__ import annotations

from datetime import datetime, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc)


def humanize_duration(seconds: float) -> str:
    """Render a raw duration in the most readable compact form."""
    s = abs(int(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        m, s = divmod(s, 60)
        return f"{m}m {s}s" if s else f"{m}m"
    if s < 86_400:
        h, rem = divmod(s, 3600)
        m = rem // 60
        return f"{h}h {m}m" if m else f"{h}h"
    d, rem = divmod(s, 86_400)
    h = rem // 3600
    return f"{d}d {h}h" if h else f"{d}d"


def humanize_eta(iso_ts: str | None) -> str:
    """Relative ETA from a UTC ISO timestamp. Returns 'in 4h 12m' or '2h ago'."""
    if not iso_ts:
        return "—"
    try:
        target = datetime.fromisoformat(iso_ts)
    except ValueError:
        return iso_ts
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    delta = (target - _now()).total_seconds()
    if abs(delta) < 5:
        return "now"
    if delta > 0:
        return f"in {humanize_duration(delta)}"
    return f"{humanize_duration(delta)} ago"


def humanize_money(amount: int | float) -> str:
    """Compact money display: $1.23T / $4.56B / $987.00M / $5.0k / $47 / -$12k.

    Thresholds use the rounded-display boundary (e.g. `>= 999.5M` rolls
    into the billion tier) so we never render '$1000.00M' or similar
    ambiguous values.
    """
    n = int(amount)
    sign = "-" if n < 0 else ""
    a = abs(n)
    if a >= 999_500_000_000:
        return f"{sign}${a / 1_000_000_000_000:.2f}T"
    if a >= 999_500_000:
        return f"{sign}${a / 1_000_000_000:.2f}B"
    if a >= 999_500:
        return f"{sign}${a / 1_000_000:.2f}M"
    if a >= 9_950:
        return f"{sign}${a / 1_000:.1f}k"
    return f"{sign}${a:,}"
