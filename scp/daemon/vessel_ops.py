"""
Ship & submarine equipment catalog + orders.

Two layers on top of the existing `ships` / `submarines` tables:

1. **Equipment** — modular gear installed on a vessel (sensor, stealth,
   comm, containment, science). Each SKU has a category, rating, capex,
   and a `fits_classes` gate. Equipment modifies order performance.

2. **Orders** — missions the player can dispatch a vessel on. Each order
   has a duration, payout, and on-complete effect. Vessels are 'busy'
   until the order completes or is cancelled. This is how ships/subs
   earn back their capex rather than sitting idle.

Order kinds implemented here:
- `patrol`            — ISR sweep; payout scales with sensor rating
- `escort_convoy`     — protect trade lanes; flat payout by hull class
- `standby_archive`   — float as secure-archive-on-station; payout scales
                        with installed archive-pod capacity
- `return_to_port`    — travel to a specified base site

Future expansion goes into DESIGN.md §24.5 (combat, ISR tracking of rival
GOI assets, torpedo engagements, MTF insertion). The module is designed
so those can land as new order kinds + new equipment categories without
reshaping anything here.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from .clock import iso, now_utc
from .journal import Journal


_TS = float(os.environ.get("SCP_TIME_SCALE", "1.0"))


def _d(seconds: float) -> float:
    return seconds * _TS


# --- equipment catalog -----------------------------------------------


@dataclass(frozen=True)
class EquipmentSku:
    sku: str
    name: str
    category: str                         # sensor | stealth | comm | containment | science
    price_usd: int
    rating: int                           # 1–10 quality score; feeds order payout
    fits_vessel_types: tuple[str, ...]    # ("ship",) / ("submarine",) / ("ship", "submarine")
    fits_classes: tuple[str, ...] | None  # None = any class of the allowed types
    capabilities: dict = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "sku": self.sku,
            "name": self.name,
            "category": self.category,
            "price_usd": self.price_usd,
            "rating": self.rating,
            "fits_vessel_types": list(self.fits_vessel_types),
            "fits_classes": list(self.fits_classes) if self.fits_classes else None,
            "capabilities": dict(self.capabilities),
            "description": self.description,
        }


EQUIPMENT: dict[str, EquipmentSku] = {}


def _add(e: EquipmentSku) -> None:
    EQUIPMENT[e.sku] = e


# Sensor suite — feeds patrol + shadow payouts and (future) detection rolls.
_add(EquipmentSku(
    "sonar-towed-passive", "Towed-array passive sonar",
    category="sensor", price_usd=500_000, rating=3,
    fits_vessel_types=("ship", "submarine"), fits_classes=None,
    description="Long-baseline passive acoustic array. Standard ISR fit.",
))
_add(EquipmentSku(
    "sonar-active-array", "Active hull-array sonar",
    category="sensor", price_usd=1_500_000, rating=5,
    fits_vessel_types=("ship", "submarine"), fits_classes=None,
    description="Active sonar. Better detection; reveals own position when pinging.",
))
_add(EquipmentSku(
    "radar-maritime", "Maritime surface-search radar",
    category="sensor", price_usd=400_000, rating=3,
    fits_vessel_types=("ship",), fits_classes=None,
    description="X-band radar for surface contacts. Ships only.",
))
_add(EquipmentSku(
    "esm-elint-suite", "ESM / ELINT intercept suite",
    category="sensor", price_usd=2_000_000, rating=4,
    fits_vessel_types=("ship", "submarine"), fits_classes=None,
    description="Passive radar + comms intercept. Feeds adversary-intel fog.",
))
_add(EquipmentSku(
    "hydrophone-array", "Anomalous-acoustic hydrophone array",
    category="sensor", price_usd=600_000, rating=3,
    fits_vessel_types=("ship", "submarine"), fits_classes=None,
    description="Listens for Class-IV-V acoustic anomalies. Niche but cheap.",
))

# Stealth — reduces detection chance (future fog-of-war consumer).
_add(EquipmentSku(
    "anechoic-coating", "Anechoic hull-tile refresh",
    category="stealth", price_usd=1_500_000, rating=4,
    fits_vessel_types=("submarine",), fits_classes=None,
    description="Rubber tiles that dampen own-noise return. Subs only.",
))

# Comms — lets vessel relay between sites / receive at depth.
_add(EquipmentSku(
    "satcom-relay", "Encrypted satcom relay node",
    category="comm", price_usd=800_000, rating=3,
    fits_vessel_types=("ship", "submarine"), fits_classes=None,
    description="Acts as a surface comm relay for allied assets in the area.",
))
_add(EquipmentSku(
    "vlf-mast", "VLF reception mast",
    category="comm", price_usd=300_000, rating=2,
    fits_vessel_types=("submarine",), fits_classes=None,
    description="Buoyant-wire VLF antenna. Subs can receive at depth.",
))

# Containment — makes the vessel act as a floating secure archive.
_add(EquipmentSku(
    "archive-pod-sm", "Modular archive pod (50 TB)",
    category="containment", price_usd=3_000_000, rating=3,
    fits_vessel_types=("ship", "submarine"),
    fits_classes=("medium", "heavy", "xluuv", "ssk", "ssk_aip", "ssn", "ssbn"),
    capabilities={"tape_cap_gb": 50_000},
    description=(
        "50 TB tape-equivalent secure archive pod. Enables standby_archive "
        "orders. Does NOT fit yachts/UUVs — needs real deck or pressure hull."
    ),
))
_add(EquipmentSku(
    "archive-pod-lg", "Modular archive pod (500 TB)",
    category="containment", price_usd=12_000_000, rating=5,
    fits_vessel_types=("ship", "submarine"),
    fits_classes=("heavy", "ssn", "ssbn"),
    capabilities={"tape_cap_gb": 500_000},
    description=(
        "500 TB secure archive pod. Heavy-hull only. For ultra-secure "
        "storage of the most dangerous archived SCPs."
    ),
))

# Science — oceanographic instruments, cover identity.
_add(EquipmentSku(
    "oceanographic-suite", "Oceanographic research suite",
    category="science", price_usd=900_000, rating=3,
    fits_vessel_types=("ship",), fits_classes=None,
    description="CTD, ROV, sample hoist. Legitimate cover for ISR work.",
))


def list_equipment(
    vessel_type: str | None = None,
    vessel_class: str | None = None,
) -> list[EquipmentSku]:
    out = []
    for e in EQUIPMENT.values():
        if vessel_type is not None and vessel_type not in e.fits_vessel_types:
            continue
        if (
            vessel_class is not None
            and e.fits_classes is not None
            and vessel_class not in e.fits_classes
        ):
            continue
        out.append(e)
    return sorted(out, key=lambda e: (e.category, e.price_usd))


def get_equipment(sku: str) -> EquipmentSku | None:
    return EQUIPMENT.get(sku)


# --- vessel resolution helper ----------------------------------------


def _resolve_vessel(journal: Journal, vessel_type: str, vessel_id: int) -> dict:
    if vessel_type == "ship":
        match = next(
            (s for s in journal.list_ships() if s["id"] == vessel_id), None
        )
    elif vessel_type == "submarine":
        match = next(
            (s for s in journal.list_submarines() if s["id"] == vessel_id), None
        )
    else:
        raise ValueError(f"vessel_type must be 'ship' or 'submarine', got '{vessel_type}'")
    if match is None:
        raise ValueError(f"no {vessel_type} with id {vessel_id}")
    return match


# --- equipment install / remove --------------------------------------


def install_equipment(
    journal: Journal, vessel_type: str, vessel_id: int, sku: str
) -> dict:
    v = _resolve_vessel(journal, vessel_type, vessel_id)
    e = get_equipment(sku)
    if e is None:
        raise ValueError(f"unknown equipment sku: {sku}")

    # Gate: vessel type + class compatibility
    if vessel_type not in e.fits_vessel_types:
        raise ValueError(
            f"'{sku}' does not fit vessel type '{vessel_type}'"
        )
    if e.fits_classes is not None and v["class"] not in e.fits_classes:
        raise ValueError(
            f"'{sku}' does not fit {vessel_type} class '{v['class']}' "
            f"(needs: {', '.join(e.fits_classes)})"
        )

    # Gate: cannot modify a vessel that's on an active order
    if v["status"] not in ("berthed", "docked", "idle"):
        raise ValueError(
            f"{vessel_type} {vessel_id} is '{v['status']}'; must be in port to refit"
        )

    current = journal.get_funding()
    if current < e.price_usd:
        raise ValueError(f"insufficient funding: ${current:,} < ${e.price_usd:,}")

    balance = journal.adjust_funding(-e.price_usd)
    eq_id = journal.install_vessel_equipment(vessel_type, int(vessel_id), sku)
    journal.append(
        "vessel_equipment_installed",
        "INFO",
        {
            "equipment_id": eq_id,
            "vessel_type": vessel_type,
            "vessel_id": vessel_id,
            "sku": sku,
            "price_usd": e.price_usd,
            "balance": balance,
        },
    )
    return {
        "equipment_id": eq_id,
        "vessel_type": vessel_type,
        "vessel_id": vessel_id,
        "sku": sku,
        "price_usd": e.price_usd,
        "balance": balance,
    }


def remove_equipment(journal: Journal, equipment_id: int) -> dict:
    row = journal.get_vessel_equipment(equipment_id)
    if row is None:
        raise ValueError(f"no equipment {equipment_id}")
    v = _resolve_vessel(journal, row["vessel_type"], row["vessel_id"])
    if v["status"] not in ("berthed", "docked", "idle"):
        raise ValueError(
            f"{row['vessel_type']} {row['vessel_id']} is '{v['status']}'; "
            f"must be in port to uninstall equipment"
        )
    journal.remove_vessel_equipment(equipment_id)
    journal.append(
        "vessel_equipment_removed", "INFO",
        {"equipment_id": equipment_id, **row},
    )
    return {"equipment_id": equipment_id, **row}


# --- equipment-derived ratings ---------------------------------------


def vessel_sensor_rating(journal: Journal, vessel_type: str, vessel_id: int) -> int:
    return sum(
        get_equipment(eq["sku"]).rating if get_equipment(eq["sku"]) else 0
        for eq in journal.list_vessel_equipment(vessel_type, vessel_id)
        if get_equipment(eq["sku"])
        and get_equipment(eq["sku"]).category == "sensor"
    )


def vessel_archive_capacity_gb(journal: Journal, vessel_type: str, vessel_id: int) -> int:
    cap = 0
    for eq in journal.list_vessel_equipment(vessel_type, vessel_id):
        e = get_equipment(eq["sku"])
        if e and e.category == "containment":
            cap += int(e.capabilities.get("tape_cap_gb", 0))
    return cap


def vessel_stealth_rating(journal: Journal, vessel_type: str, vessel_id: int) -> int:
    return sum(
        get_equipment(eq["sku"]).rating if get_equipment(eq["sku"]) else 0
        for eq in journal.list_vessel_equipment(vessel_type, vessel_id)
        if get_equipment(eq["sku"])
        and get_equipment(eq["sku"]).category == "stealth"
    )


# --- orders ----------------------------------------------------------


ORDER_KINDS = (
    "patrol", "escort_convoy", "standby_archive", "return_to_port"
)


# hull-class multiplier applied to flat order payouts
_CLASS_MULT = {
    # surface
    "small": 1.0,
    "medium": 1.5,
    "heavy": 2.5,
    # sub
    "uuv": 0.3,
    "xluuv": 0.8,
    "ssk": 1.5,
    "ssk_aip": 1.8,
    "ssn": 3.0,
    "ssbn": 5.0,
}


def _class_mult(vessel_class: str) -> float:
    return _CLASS_MULT.get(vessel_class, 1.0)


def order_vessel(
    journal: Journal,
    schedule_fn: Any,
    vessel_type: str,
    vessel_id: int,
    kind: str,
    hours: float | None = None,
    target_site_id: int | None = None,
) -> dict:
    if kind not in ORDER_KINDS:
        raise ValueError(
            f"unknown order '{kind}'; valid: {', '.join(ORDER_KINDS)}"
        )
    v = _resolve_vessel(journal, vessel_type, vessel_id)

    # Already busy?
    if journal.get_active_vessel_order(vessel_type, vessel_id) is not None:
        raise ValueError(
            f"{vessel_type} {vessel_id} already has an active order; "
            f"cancel_order first"
        )

    mult = _class_mult(v["class"])
    params: dict[str, Any] = {}
    payout = 0
    duration_h = hours or 6.0

    if kind == "patrol":
        sensor = vessel_sensor_rating(journal, vessel_type, vessel_id)
        if sensor <= 0:
            raise ValueError(
                f"patrol requires at least one sensor installed "
                f"(current sensor rating = 0)"
            )
        # $5k/h base × hull mult × (1 + sensor/10)
        payout = int(5_000 * duration_h * mult * (1 + sensor / 10))
        params = {"sensor_rating": sensor, "hours": duration_h}

    elif kind == "escort_convoy":
        # Flat payout per mission by hull mult. Medium=6h, heavy=8h, sub-slower
        payout = int(40_000 * mult)
        params = {"hours": duration_h}

    elif kind == "standby_archive":
        cap = vessel_archive_capacity_gb(journal, vessel_type, vessel_id)
        if cap <= 0:
            raise ValueError(
                f"standby_archive requires an archive-pod installed "
                f"(current archive capacity = 0 GB)"
            )
        # O5 pays a commission for secure offshore archive:
        # $1k/h per 10 TB of pod capacity, scaled by hours.
        payout = int(1_000 * duration_h * (cap / 10_000))
        params = {"archive_cap_gb": cap, "hours": duration_h}

    elif kind == "return_to_port":
        if target_site_id is None:
            raise ValueError("return_to_port requires target_site_id")
        if not any(s["id"] == target_site_id for s in journal.list_sites()):
            raise ValueError(f"no site with id {target_site_id}")
        if int(v["site_id"]) == int(target_site_id):
            raise ValueError(
                f"{vessel_type} {vessel_id} already at site {target_site_id}"
            )
        payout = 0
        duration_h = hours or 4.0
        params = {"target_site_id": int(target_site_id), "hours": duration_h}

    # Schedule completion
    duration_s = _d(duration_h * 3600)
    eta = now_utc() + timedelta(seconds=duration_s)
    order_id = journal.create_vessel_order(
        vessel_type=vessel_type,
        vessel_id=int(vessel_id),
        kind=kind,
        params_json=json.dumps(params),
        eta_iso=iso(eta),
        payout_usd=int(payout),
    )
    sid = schedule_fn(eta, "vessel_order_complete", {"order_id": int(order_id)})
    journal.set_vessel_order_scheduled_id(order_id, int(sid))

    # Mark vessel busy
    at_sea = "submerged" if vessel_type == "submarine" else "at_sea"
    journal.set_vessel_status(vessel_type, int(vessel_id), at_sea)

    journal.append(
        "vessel_order_issued",
        "INFO",
        {
            "order_id": order_id,
            "vessel_type": vessel_type,
            "vessel_id": vessel_id,
            "kind": kind,
            "params": params,
            "payout_usd": payout,
            "eta": iso(eta),
            "scheduled_id": sid,
        },
    )
    return {
        "order_id": order_id,
        "vessel_type": vessel_type,
        "vessel_id": vessel_id,
        "kind": kind,
        "params": params,
        "payout_usd": payout,
        "eta": iso(eta),
        "scheduled_id": sid,
    }


def cancel_order(journal: Journal, vessel_type: str, vessel_id: int) -> dict:
    row = journal.get_active_vessel_order(vessel_type, vessel_id)
    if row is None:
        raise ValueError(f"{vessel_type} {vessel_id} has no active order")
    journal.set_vessel_order_state(int(row["id"]), "cancelled")
    berth = "berthed"
    journal.set_vessel_status(vessel_type, int(vessel_id), berth)
    journal.append(
        "vessel_order_cancelled", "NOTICE",
        {
            "order_id": row["id"],
            "vessel_type": vessel_type,
            "vessel_id": vessel_id,
            "kind": row["kind"],
        },
    )
    return {"order_id": row["id"], "kind": row["kind"]}


def on_order_complete(journal: Journal, order_id: int) -> dict:
    row = journal.get_vessel_order(order_id)
    if row is None:
        return {"error": f"no order {order_id}"}
    if row["state"] != "active":
        # Cancelled or already finalized — nothing to do.
        return {"order_id": order_id, "state": row["state"]}

    kind = row["kind"]
    try:
        params = json.loads(row["params_json"] or "{}")
    except json.JSONDecodeError:
        params = {}

    balance = journal.get_funding()
    payout = int(row.get("payout_usd", 0) or 0)
    effect: dict[str, Any] = {"payout_usd": payout}

    if payout:
        balance = journal.adjust_funding(payout)

    if kind == "return_to_port":
        target = int(params.get("target_site_id"))
        journal.set_vessel_site(row["vessel_type"], int(row["vessel_id"]), target)
        effect["site_id"] = target

    # Mark order complete + vessel berthed
    journal.set_vessel_order_state(order_id, "complete", json.dumps(effect))
    journal.set_vessel_status(
        row["vessel_type"], int(row["vessel_id"]), "berthed"
    )

    journal.append(
        "vessel_order_complete", "INFO",
        {
            "order_id": order_id,
            "vessel_type": row["vessel_type"],
            "vessel_id": row["vessel_id"],
            "kind": kind,
            "effect": effect,
            "balance": balance,
        },
    )
    return {
        "order_id": order_id,
        "vessel_type": row["vessel_type"],
        "vessel_id": row["vessel_id"],
        "kind": kind,
        "effect": effect,
        "balance": balance,
    }
