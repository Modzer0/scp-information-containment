from __future__ import annotations

from .clock import iso, now_utc
from .journal import Journal


CATEGORY_SEVERITY = {
    "stable": "INFO",
    "slow_leak": "NOTICE",
    "active_leak": "ALERT",
    "catastrophic": "BREACH",
}


def category_recommendations(category: str) -> list[str]:
    if category == "slow_leak":
        return [
            "flag VM as tainted; snapshot-restore before reuse",
            "refresh scanner signature feed",
        ]
    if category == "active_leak":
        return [
            "immediately air-gap the affected host's subnet",
            "schedule forensic wipe of the VM substrate",
            "trigger mnestic protocol for the operator",
        ]
    if category == "catastrophic":
        return [
            "isolate and forensic-wipe host and all VMs on it",
            "mnestic protocol + stand-down for exposed staff",
            "rotate operator assignments",
            "uplift containment tier before re-attempting this item class",
        ]
    return []


def build_report(
    *,
    item: dict,
    host: dict,
    vm: dict,
    operator: dict | None,
    category: str,
    hazard: int,
    containment: int,
    mistake_records: list[dict],
) -> tuple[str, str, str, list[str], dict, list[str]]:
    """Returns (report_text, severity, root_cause, contributing, exposure, recommend).
    Persisting to SQLite is the caller's responsibility.
    """
    severity = CATEGORY_SEVERITY.get(category, "INFO")
    delta = hazard - containment
    op_name = operator["name"] if operator else "unknown-operator"
    op_skill = int(operator["skills"].get("infosec", 0)) if operator else 0
    op_id = operator["id"] if operator else None

    # Root cause: the highest severity_weight mistake wins.
    if mistake_records:
        ordered = sorted(
            mistake_records,
            key=lambda m: -int(m.get("details", {}).get("severity_weight", 1)),
        )
        primary = ordered[0]
        root_cause = f"{primary['kind']}: {primary['details'].get('title', '')}"
        contributing = [
            f"{m['kind']}: {m['details'].get('title', '')}"
            for m in ordered[1:]
        ]
    else:
        root_cause = f"{category} with delta={delta} (no mistake detectors tripped)"
        contributing = []

    exposure = {
        "item_id": item["id"],
        "vm_id": vm["id"],
        "host_id": host["id"],
        "category": category,
        "delta": delta,
        "memetic_load": item.get("profile", {}).get("memetic_load"),
        "self_propagation": item.get("profile", {}).get("self_propagation"),
    }

    recommend = category_recommendations(category)

    # Formatted report (multi-line, fixed-width to look like a real SOC ticket)
    lines = []
    lines.append(
        f"INCIDENT (pending ID) · SEV: {severity} · {iso(now_utc())}"
    )
    lines.append("")
    lines.append(
        f"ITEM        {item['designation']} "
        f"(class: {item['class']}, hazard: {hazard}, "
        f"memetic_load: {item.get('profile', {}).get('memetic_load', 0)}, "
        f"self_propagation: {item.get('profile', {}).get('self_propagation', 0)})"
    )
    lines.append(
        f"HOST        {host['name']} ({host['status']})"
    )
    lines.append(
        f"VM          {vm['name']} (containment: {containment}, state: {vm['status']})"
    )
    lines.append(
        f"VECTOR      analyze issued by {op_name} (skill {op_skill})"
    )
    lines.append("")
    lines.append(f"ROOT CAUSE  {root_cause}")
    if contributing:
        lines.append("")
        lines.append("CONTRIBUTING")
        for c in contributing:
            lines.append(f"  - {c}")
    lines.append("")
    lines.append(
        f"EXPOSURE    category={category}, delta={delta}, "
        f"memetic_load={exposure['memetic_load']}, "
        f"self_propagation={exposure['self_propagation']}"
    )
    if recommend:
        lines.append("RECOMMEND")
        for r in recommend:
            lines.append(f"  - {r}")
    lines.append("")
    lines.append(
        f"OPERATOR    id={op_id} skill_infosec={op_skill}"
    )

    report_text = "\n".join(lines)
    return report_text, severity, root_cause, contributing, exposure, recommend


def persist(
    journal: Journal,
    *,
    item: dict,
    host: dict,
    vm: dict,
    operator: dict | None,
    category: str,
    hazard: int,
    containment: int,
    mistake_ids: list[int],
) -> int:
    mistake_records: list[dict] = []
    for mid in mistake_ids:
        for m in journal.recent_mistakes(200):
            if m["id"] == mid:
                mistake_records.append(m)
                break

    report_text, severity, root_cause, contributing, exposure, recommend = build_report(
        item=item,
        host=host,
        vm=vm,
        operator=operator,
        category=category,
        hazard=hazard,
        containment=containment,
        mistake_records=mistake_records,
    )

    incident_id = journal.create_incident(
        severity=severity,
        item_id=item["id"],
        host_id=host["id"],
        vm_id=vm["id"],
        operator_id=(operator["id"] if operator else None),
        vector="analyze",
        root_cause=root_cause,
        contributing=contributing,
        exposure=exposure,
        recommend=recommend,
        mistake_ids=mistake_ids,
        report=report_text,
    )
    return incident_id
