from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from .clock import from_iso, iso, now_utc
from .journal import Journal


_TS = float(os.environ.get("SCP_TIME_SCALE", "1.0"))


def _d(seconds: float) -> float:
    return seconds * _TS


@dataclass(frozen=True)
class ContractType:
    type_id: str
    name: str
    description: str
    cost_per_period: int
    period_seconds: float        # pre-scaled
    target: str                  # "vm" | "site" | "aircraft" | "ship" | "none"


TYPES: dict[str, ContractType] = {}


def _add(ct: ContractType) -> None:
    TYPES[ct.type_id] = ct


_add(ContractType(
    "scanner_feed",
    "Live scanner signature feed",
    "Maintains target VM scanner_freshness=2. Lapse drops to 0.",
    cost_per_period=5_000,
    period_seconds=_d(7 * 86_400),   # weekly billing
    target="vm",
))
_add(ContractType(
    "diesel_supply",
    "Diesel genset supply contract",
    "Keeps a genset-powered site fueled. Lapse: site power capacity effectively 0 "
    "until re-subscribed.",
    cost_per_period=8_000,
    period_seconds=_d(7 * 86_400),
    target="site",
))
_add(ContractType(
    "jet_a_supply",
    "Jet-A aviation fuel supply",
    "Per-aircraft Jet-A delivery. Lapse: aircraft status → maintenance (no ops, "
    "no transfer discount).",
    cost_per_period=2_000,
    period_seconds=_d(7 * 86_400),
    target="aircraft",
))
_add(ContractType(
    "bunker_fuel",
    "Marine bunker fuel supply",
    "Per-ship bunker / MGO delivery. Lapse: ship status → maintenance.",
    cost_per_period=5_000,
    period_seconds=_d(7 * 86_400),
    target="ship",
))

# --- Guard contracts (security layer) --------------------------------
# Bonuses live in security.GUARD_CONTRACT_BONUS keyed by these type_ids.
# Monthly billing (30-day period).
_add(ContractType(
    "guard_watch_single",
    "Single watch guard (8h/day)",
    "One licensed guard, day shift only. +3 to site security rating.",
    cost_per_period=6_000,
    period_seconds=_d(30 * 86_400),
    target="site",
))
_add(ContractType(
    "guard_watch_shift",
    "24/7 guard rotation (4 guards)",
    "Four-guard rotation covering all shifts. +8 to site security rating.",
    cost_per_period=20_000,
    period_seconds=_d(30 * 86_400),
    target="site",
))
_add(ContractType(
    "pmsc_team_light",
    "PMSC armed detail (6 operators)",
    "Light armed detail: 6 PMSC operators with SOP for static defense. +15.",
    cost_per_period=50_000,
    period_seconds=_d(30 * 86_400),
    target="site",
))
_add(ContractType(
    "pmsc_team_heavy",
    "PMSC armed + QRF (12 operators)",
    "Heavy armed detail plus quick-reaction force. +25 to site rating.",
    cost_per_period=120_000,
    period_seconds=_d(30 * 86_400),
    target="site",
))
_add(ContractType(
    "mtf_squad",
    "Mobile Task Force squad (8 operators)",
    "Foundation MTF squad — trained for anomalous-object protection. +40.",
    cost_per_period=250_000,
    period_seconds=_d(30 * 86_400),
    target="site",
))


def list_types() -> list[ContractType]:
    return sorted(TYPES.values(), key=lambda c: c.type_id)


def get_type(type_id: str) -> ContractType | None:
    return TYPES.get(type_id)


# --- effects ----------------------------------------------------------


def _apply_start(journal: Journal, contract_type: str, target_id: int | None) -> None:
    """Effect when a contract becomes active."""
    if contract_type == "scanner_feed" and target_id is not None:
        vm = journal.get_vm(target_id)
        if vm:
            spec = dict(vm["spec"])
            spec["scanner_freshness"] = max(int(spec.get("scanner_freshness", 0)), 2)
            journal.update_vm_spec(target_id, spec)
    # jet_a_supply / bunker_fuel have no start-side effect (asset already parked/berthed)


def _apply_lapse(journal: Journal, contract_type: str, target_id: int | None) -> None:
    """Effect when a contract lapses or is cancelled."""
    if contract_type == "scanner_feed" and target_id is not None:
        vm = journal.get_vm(target_id)
        if vm:
            spec = dict(vm["spec"])
            spec["scanner_freshness"] = 0
            journal.update_vm_spec(target_id, spec)
    # Aircraft / ship fuel lapses move the asset to maintenance status.
    if contract_type == "jet_a_supply" and target_id is not None:
        journal._conn.execute(
            "UPDATE aircraft SET status = 'maintenance' WHERE id = ?",
            (target_id,),
        )
    if contract_type == "bunker_fuel" and target_id is not None:
        journal._conn.execute(
            "UPDATE ships SET status = 'maintenance' WHERE id = ?",
            (target_id,),
        )


# --- lifecycle --------------------------------------------------------


def subscribe(
    journal: Journal,
    schedule_fn: Any,
    type_id: str,
    target_vm_id: int | None = None,
    target_site_id: int | None = None,
    target_asset_id: int | None = None,
) -> dict:
    """target_asset_id carries aircraft-id or ship-id for those contract types."""
    ct = get_type(type_id)
    if ct is None:
        raise ValueError(f"unknown contract type: {type_id}")

    # Normalize target id into target_vm_id slot for contract row (aircraft/ship
    # share the vm-id column for MVP — distinguished by contract_type).
    if ct.target == "vm":
        if target_vm_id is None:
            raise ValueError(f"contract {type_id} requires target_vm_id")
        if journal.get_vm(target_vm_id) is None:
            raise ValueError(f"no vm {target_vm_id}")
        target_site_id = None
    elif ct.target == "site":
        if target_site_id is None:
            raise ValueError(f"contract {type_id} requires target_site_id")
        target_vm_id = None
    elif ct.target in ("aircraft", "ship"):
        if target_asset_id is None:
            raise ValueError(
                f"contract {type_id} requires target_asset_id (aircraft/ship id)"
            )
        # Stash asset id in the target_vm_id slot so existing duplicate-check works.
        target_vm_id = target_asset_id
        target_site_id = None

    existing = journal.list_contracts(
        status="active", contract_type=type_id, target_vm_id=target_vm_id
    )
    if existing:
        raise ValueError(
            f"active {type_id} contract already exists (#{existing[0]['id']})"
        )

    # First period payment
    if journal.get_funding() < ct.cost_per_period:
        raise ValueError(
            f"insufficient funding for first period: "
            f"${journal.get_funding():,} < ${ct.cost_per_period:,}"
        )
    balance = journal.adjust_funding(-ct.cost_per_period)

    next_bill = now_utc() + timedelta(seconds=ct.period_seconds)
    contract_id = journal.create_contract(
        contract_type=type_id,
        target_site_id=target_site_id,
        target_vm_id=target_vm_id,
        cost_per_period=ct.cost_per_period,
        period_seconds=ct.period_seconds,
        details={"type_name": ct.name},
        next_billing_utc=next_bill,
    )
    _apply_start(journal, type_id, target_vm_id if ct.target == "vm" else target_site_id)
    sid = schedule_fn(
        next_bill, "contract_billing", {"contract_id": contract_id}
    )
    journal.append(
        "contract_subscribed",
        "INFO",
        {
            "contract_id": contract_id,
            "type": type_id,
            "target_vm_id": target_vm_id,
            "target_site_id": target_site_id,
            "first_period_cost": ct.cost_per_period,
            "balance": balance,
            "next_billing": iso(next_bill),
            "scheduled_id": sid,
        },
    )
    return {
        "contract_id": contract_id,
        "type": type_id,
        "next_billing": iso(next_bill),
        "balance": balance,
    }


def cancel(journal: Journal, contract_id: int) -> dict:
    c = journal.get_contract(contract_id)
    if not c:
        raise ValueError(f"no contract {contract_id}")
    if c["status"] != "active":
        raise ValueError(f"contract {contract_id} is {c['status']}")
    journal.set_contract_status(contract_id, "cancelled")
    _apply_lapse(
        journal, c["contract_type"],
        c["target_vm_id"] if c["target_vm_id"] is not None else c["target_site_id"],
    )
    journal.append(
        "contract_cancelled", "INFO",
        {"contract_id": contract_id, "type": c["contract_type"]},
    )
    return {"contract_id": contract_id, "status": "cancelled"}


def on_billing(
    journal: Journal, schedule_fn: Any, contract_id: int
) -> dict:
    c = journal.get_contract(contract_id)
    if not c:
        return {"error": f"no contract {contract_id}"}
    if c["status"] != "active":
        return {"contract_id": contract_id, "status": c["status"], "skipped": True}

    cost = int(c["cost_per_period"])
    if journal.get_funding() < cost:
        # Lapse
        journal.set_contract_status(contract_id, "lapsed")
        _apply_lapse(
            journal, c["contract_type"],
            c["target_vm_id"] if c["target_vm_id"] is not None
            else c["target_site_id"],
        )
        result = {
            "contract_id": contract_id,
            "status": "lapsed",
            "reason": "insufficient_funds",
            "type": c["contract_type"],
        }
        journal.append("contract_lapsed", "ALERT", result)
        return result

    new_balance = journal.adjust_funding(-cost)
    next_bill = now_utc() + timedelta(seconds=float(c["period_seconds"]))
    journal.set_contract_next_billing(contract_id, next_bill)
    sid = schedule_fn(
        next_bill, "contract_billing", {"contract_id": contract_id}
    )
    result = {
        "contract_id": contract_id,
        "status": "billed",
        "type": c["contract_type"],
        "cost": cost,
        "balance": new_balance,
        "next_billing": iso(next_bill),
        "scheduled_id": sid,
    }
    journal.append("contract_billed", "INFO", result)
    return result
