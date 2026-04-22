from __future__ import annotations

from typing import Any

from .journal import Journal


# Per-site playbook rules. Each is a named flag the player toggles.
KNOWN_RULES = {
    "auto_acquire_safe": (
        "When a scan completes, automatically acquire all Safe-class candidates."
    ),
    "auto_archive_analyzed": (
        "When an analysis ends stable, automatically archive the item."
    ),
    "auto_wipe_infected": (
        "When a host becomes infected, automatically start a forensic wipe."
    ),
}


def known_rules() -> list[dict]:
    return [{"rule": k, "description": v} for k, v in KNOWN_RULES.items()]


def get_site_rules(journal: Journal, site_id: int) -> dict:
    return dict(journal.get_playbook(site_id))


def set_site_rule(
    journal: Journal, site_id: int, rule: str, enabled: bool
) -> dict:
    if rule not in KNOWN_RULES:
        raise ValueError(f"unknown playbook rule: {rule}")
    rules = dict(journal.get_playbook(site_id))
    rules[rule] = bool(enabled)
    journal.set_playbook(site_id, rules)
    journal.append(
        "playbook_rule_changed",
        "INFO",
        {"site_id": site_id, "rule": rule, "enabled": bool(enabled)},
    )
    return rules


# --- triggers called from _on_fire after gameplay handlers ------------


def apply_post_scan(
    journal: Journal, schedule_fn: Any, item_ids: list[int]
) -> list[dict]:
    """After a scan completes, auto-acquire Safe-class candidates for sites
    with that rule enabled. Silent on per-item failures."""
    from . import gameplay

    triggered: list[dict] = []
    for site in journal.list_sites():
        rules = get_site_rules(journal, site["id"])
        if not rules.get("auto_acquire_safe"):
            continue
        for iid in item_ids:
            item = journal.get_item(iid)
            if (
                item
                and item["class"] == "Safe"
                and item["state"] == "candidate"
            ):
                try:
                    gameplay.acquire_candidate(journal, iid)
                    triggered.append(
                        {"rule": "auto_acquire_safe", "item_id": iid}
                    )
                except ValueError:
                    pass
    if triggered:
        journal.append("playbook_triggered", "INFO", {"triggered": triggered})
    return triggered


def apply_post_analyze(
    journal: Journal,
    schedule_fn: Any,
    item_id: int,
    category: str,
    host_id: int | None,
) -> list[dict]:
    """After an analysis completes, maybe auto-archive (if stable) or
    auto-wipe (if host now infected)."""
    from . import gameplay

    triggered: list[dict] = []

    # auto-archive on stable outcome
    if category == "stable":
        for site in journal.list_sites():
            rules = get_site_rules(journal, site["id"])
            if not rules.get("auto_archive_analyzed"):
                continue
            try:
                gameplay.start_archive(journal, schedule_fn, item_id)
                triggered.append(
                    {"rule": "auto_archive_analyzed", "item_id": item_id}
                )
                break
            except ValueError:
                pass

    # auto-wipe on host infection
    if (
        host_id is not None
        and category in ("active_leak", "catastrophic")
    ):
        host = journal.get_host(host_id)
        if host and host.get("status") == "infected":
            for site in journal.list_sites():
                rules = get_site_rules(journal, site["id"])
                if not rules.get("auto_wipe_infected"):
                    continue
                try:
                    gameplay.start_wipe(journal, schedule_fn, host_id)
                    triggered.append(
                        {"rule": "auto_wipe_infected", "host_id": host_id}
                    )
                    break
                except ValueError:
                    pass

    if triggered:
        journal.append("playbook_triggered", "INFO", {"triggered": triggered})
    return triggered
