"""
Site security layer.

Every site has a numeric security_rating computed as:

    rating = BASE[site_type]
           + sum(installed_equipment_bonuses)
           + sum(active_guard_contract_bonuses)

Ratings drive a daily incident roll — sites below 50 risk theft,
sabotage, or attempted breaches. Sites at 50+ are effectively safe.

This is the foundation layer for the rival-GOI detection + raid
mechanics sketched in DESIGN §24.5: the same IMINT/COMINT/ELINT
equipment that hardens your own sites will, in a future phase, surface
rival sites on the map.
"""
from __future__ import annotations

import os
import random
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from .clock import iso, now_utc
from .journal import Journal


_TS = float(os.environ.get("SCP_TIME_SCALE", "1.0"))


def _d(seconds: float) -> float:
    return seconds * _TS


# --- base rating by site type ----------------------------------------
#
# Numbers are tuned so the cheapest/most-exposed hulls (tent, field
# kit) default to a level where incidents are common, and the hardened
# hulls (subsea_pod, underground) are near-invulnerable without any
# extra gear. The player builds up the middle tier with equipment and
# guard contracts.

BASE_RATING: dict[str, int] = {
    "tent":            5,
    "field_site":      8,
    "office_closet":  10,
    "mobidc":         15,
    "onprem_dc":      25,
    "oil_platform":   30,
    "bunker_shallow": 45,
    "antarctica":     50,
    "underground":    70,
    "subsea_pod":     80,
}


def base_rating(site_type: str) -> int:
    return BASE_RATING.get(site_type, 10)


# --- equipment catalog -----------------------------------------------


@dataclass(frozen=True)
class SecuritySku:
    sku: str
    name: str
    category: str                    # physical | access | detection | shielding | signals
    price_usd: int
    rating_bonus: int
    blocked_site_types: tuple[str, ...] = ()   # e.g. tent can't mount blast doors
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "sku": self.sku,
            "name": self.name,
            "category": self.category,
            "price_usd": self.price_usd,
            "rating_bonus": self.rating_bonus,
            "blocked_site_types": list(self.blocked_site_types),
            "description": self.description,
        }


EQUIPMENT: dict[str, SecuritySku] = {}


def _add_eq(s: SecuritySku) -> None:
    EQUIPMENT[s.sku] = s


# Physical / perimeter
_add_eq(SecuritySku(
    "perimeter-fence", "Perimeter fence + signage",
    category="physical", price_usd=50_000, rating_bonus=5,
    blocked_site_types=("subsea_pod",),
    description="Chainlink + razor wire + keep-out signage. Ground sites only.",
))
_add_eq(SecuritySku(
    "safe-room-vault", "Hardened safe room / document vault",
    category="physical", price_usd=250_000, rating_bonus=8,
    description="Last-retreat space + offline key storage. Slows insider exfil.",
))
_add_eq(SecuritySku(
    "blast-doors", "Reinforced blast doors",
    category="physical", price_usd=800_000, rating_bonus=12,
    blocked_site_types=("tent", "field_site"),
    description="Buys time against forced entry; pairs with access control.",
))

# Access control
_add_eq(SecuritySku(
    "access-control-system", "RFID + biometric mantrap",
    category="access", price_usd=150_000, rating_bonus=8,
    description="Card + fingerprint readers with mantrap interlock. Logs everything.",
))

# Detection / surveillance
_add_eq(SecuritySku(
    "cctv-network", "CCTV + NVR recording",
    category="detection", price_usd=80_000, rating_bonus=5,
    description="PoE IP cameras + on-prem NVR with 30-day retention.",
))
_add_eq(SecuritySku(
    "motion-sensors", "Passive-IR + microwave sensors",
    category="detection", price_usd=120_000, rating_bonus=6,
    description="Dual-tech perimeter and interior sensors. Reduces silent-infiltration chance.",
))
_add_eq(SecuritySku(
    "counter-drone-system", "Counter-UAS: detect + soft-kill",
    category="detection", price_usd=500_000, rating_bonus=10,
    blocked_site_types=("subsea_pod",),
    description="Drone RF detection + jam/take-over. Blocks small-UAV overflight ISR.",
))
_add_eq(SecuritySku(
    "honeypot-network", "Honeypot / deception network",
    category="detection", price_usd=200_000, rating_bonus=7,
    description="Decoy VMs + fake archive metadata. Catches insiders and red teams.",
))

# EM / shielding
_add_eq(SecuritySku(
    "rf-faraday-shielding", "RF Faraday cage + TEMPEST shielding",
    category="shielding", price_usd=300_000, rating_bonus=8,
    description=(
        "Metallic shielding stops emanation eavesdropping. Cuts COMINT risk, "
        "improves memetic quarantine."
    ),
))

# Signals — IMINT/COMINT/ELINT (these are the extension hook for §24.6:
# once the rival-GOI layer lands, these also feed detection scores).
_add_eq(SecuritySku(
    "comint-mast", "COMINT intercept mast",
    category="signals", price_usd=1_200_000, rating_bonus=4,
    description=(
        "Monitors inbound RF probing of your site — counterintel only today, "
        "will feed rival-GOI detection in §24.6."
    ),
))
_add_eq(SecuritySku(
    "elint-array", "ELINT emitter-fingerprint array",
    category="signals", price_usd=2_000_000, rating_bonus=6,
    description=(
        "Catalogues hostile radar/comms emitters near your site. Counterintel "
        "today; rival-site geolocation in §24.6."
    ),
))
_add_eq(SecuritySku(
    "imint-dome", "IMINT optical + SAR dome",
    category="signals", price_usd=1_500_000, rating_bonus=4,
    description=(
        "Fixed optical + synthetic-aperture radar dome. Spots approaching "
        "threats; images rival sites in §24.6."
    ),
))


def list_equipment() -> list[SecuritySku]:
    return sorted(EQUIPMENT.values(), key=lambda s: (s.category, s.price_usd))


def get_equipment(sku: str) -> SecuritySku | None:
    return EQUIPMENT.get(sku)


# --- guard contract catalog (separate from equipment; lives in
#     contracts.py so it integrates with recurring billing / lapse) ----

# Bonus values keyed by contract_type — read by compute_rating() to
# add the right boost when a guard contract is active on a site.
GUARD_CONTRACT_BONUS: dict[str, int] = {
    "guard_watch_single": 3,
    "guard_watch_shift":  8,
    "pmsc_team_light":   15,
    "pmsc_team_heavy":   25,
    "mtf_squad":         40,
}


# --- rating computation ----------------------------------------------


def compute_rating(journal: Journal, site_id: int) -> dict:
    sites = journal.list_sites()
    match = next((s for s in sites if s["id"] == site_id), None)
    if match is None:
        return {"site_id": site_id, "error": "no such site"}
    base = base_rating(match["type"])

    eq_bonus = 0
    equipment = journal.list_site_security(site_id)
    for row in equipment:
        e = get_equipment(row["sku"])
        if e:
            eq_bonus += e.rating_bonus

    guard_bonus = 0
    guard_contracts = [
        c for c in journal.list_contracts(status="active")
        if c["target_site_id"] == site_id
        and c["contract_type"] in GUARD_CONTRACT_BONUS
    ]
    for c in guard_contracts:
        guard_bonus += GUARD_CONTRACT_BONUS.get(c["contract_type"], 0)

    total = base + eq_bonus + guard_bonus
    return {
        "site_id": site_id,
        "site_name": match["name"],
        "site_type": match["type"],
        "base": base,
        "equipment_bonus": eq_bonus,
        "guard_bonus": guard_bonus,
        "total": total,
        "equipment_count": len(equipment),
        "guard_contracts": [c["id"] for c in guard_contracts],
    }


def all_ratings(journal: Journal) -> list[dict]:
    return [compute_rating(journal, s["id"]) for s in journal.list_sites()]


# --- equipment install / remove --------------------------------------


def install_equipment(journal: Journal, site_id: int, sku: str) -> dict:
    sku_def = get_equipment(sku)
    if sku_def is None:
        raise ValueError(f"unknown security sku: {sku}")
    match = next((s for s in journal.list_sites() if s["id"] == site_id), None)
    if match is None:
        raise ValueError(f"no site with id {site_id}")
    if match["type"] in sku_def.blocked_site_types:
        raise ValueError(
            f"'{sku}' cannot be installed on site type '{match['type']}'"
        )
    current = journal.get_funding()
    if current < sku_def.price_usd:
        raise ValueError(
            f"insufficient funding: ${current:,} < ${sku_def.price_usd:,}"
        )
    balance = journal.adjust_funding(-sku_def.price_usd)
    eq_id = journal.install_site_security(site_id, sku)
    journal.append(
        "security_equipment_installed",
        "INFO",
        {
            "equipment_id": eq_id,
            "site_id": site_id,
            "sku": sku,
            "price_usd": sku_def.price_usd,
            "rating_bonus": sku_def.rating_bonus,
            "balance": balance,
        },
    )
    return {
        "equipment_id": eq_id,
        "site_id": site_id,
        "sku": sku,
        "price_usd": sku_def.price_usd,
        "rating_bonus": sku_def.rating_bonus,
        "balance": balance,
    }


def remove_equipment(journal: Journal, equipment_id: int) -> dict:
    row = journal.get_site_security_row(equipment_id)
    if row is None:
        raise ValueError(f"no security equipment {equipment_id}")
    journal.remove_site_security(equipment_id)
    journal.append(
        "security_equipment_removed", "INFO",
        {"equipment_id": equipment_id, **row},
    )
    return {"equipment_id": equipment_id, **row}


# --- incident rolls --------------------------------------------------

# Daily (game time) roll frequency — period seconds pre-scaled.
ROLL_PERIOD_S = _d(24 * 3600)


def schedule_next_roll(schedule_fn: Any) -> int:
    eta = now_utc() + timedelta(seconds=ROLL_PERIOD_S)
    return schedule_fn(eta, "security_roll", {})


def _incident_chance(rating: int) -> float:
    """Ratings >= 50 are safe. Below 50, chance scales linearly to 50%
    at rating 0."""
    if rating >= 50:
        return 0.0
    return (50 - rating) / 100.0


INCIDENT_WEIGHTS = (
    ("attempted_breach", 50),
    ("sabotage_power", 20),
    ("sabotage_host", 20),
    ("theft",          10),
)


def _pick_incident(rng: random.Random) -> str:
    total = sum(w for _, w in INCIDENT_WEIGHTS)
    roll = rng.randint(1, total)
    acc = 0
    for name, w in INCIDENT_WEIGHTS:
        acc += w
        if roll <= acc:
            return name
    return INCIDENT_WEIGHTS[-1][0]


def _apply_incident(
    journal: Journal, site_id: int, rating_info: dict, kind: str,
    rng: random.Random,
) -> dict:
    """Apply a single incident to a site. Returns a result dict."""
    details: dict[str, Any] = {
        "site_id": site_id,
        "site_name": rating_info["site_name"],
        "rating": rating_info["total"],
        "kind": kind,
    }

    if kind == "attempted_breach":
        # Equipment/guards caught it; no damage.
        details["outcome"] = "deterred"
        journal.append("security_incident", "NOTICE", details)
        return details

    if kind == "sabotage_power":
        # Fabricate a 2h outage via the existing outages table.
        eta_end = now_utc() + timedelta(seconds=_d(2 * 3600))
        journal.create_outage(
            site_id=site_id, kind="sabotage",
            duration_h=2.0, ride_through=False, eta_end_utc=eta_end,
        )
        details["outcome"] = "power_outage_2h"
        journal.append("security_incident", "ALERT", details)
        return details

    if kind == "sabotage_host":
        # Pick a random clean host at the site and flip to 'suspect'.
        hosts = [
            h for h in journal.list_hosts()
            if h["site_id"] == site_id and h["status"] == "clean"
        ]
        if not hosts:
            # Downgrade to attempted_breach if nothing to sabotage.
            details["kind"] = "attempted_breach"
            details["outcome"] = "deterred"
            details["reason"] = "no clean host at site"
            journal.append("security_incident", "NOTICE", details)
            return details
        victim = rng.choice(hosts)
        journal.set_host_status(victim["id"], "suspect")
        details["outcome"] = "host_suspect"
        details["host_id"] = victim["id"]
        details["host_name"] = victim["name"]
        journal.append("security_incident", "ALERT", details)
        return details

    if kind == "theft":
        # Pick a random archived item at the site → state='stolen'.
        items = [
            i for i in journal.list_items(state="archived")
            if i.get("current_site_id") == site_id
        ]
        if not items:
            details["kind"] = "attempted_breach"
            details["outcome"] = "deterred"
            details["reason"] = "no archive to steal"
            journal.append("security_incident", "NOTICE", details)
            return details
        victim = rng.choice(items)
        journal.set_item_state(victim["id"], "stolen", current_vm_id=None)
        details["outcome"] = "item_stolen"
        details["item_id"] = victim["id"]
        details["designation"] = victim["designation"]
        details["item_class"] = victim.get("class")
        journal.append("security_incident", "ALERT", details)
        return details

    return details


def on_roll(
    journal: Journal, schedule_fn: Any, rng: random.Random
) -> dict:
    """Fire once per game-day. Rolls each site, applies any incidents,
    and queues the next roll."""
    triggered: list[dict] = []
    for s in journal.list_sites():
        info = compute_rating(journal, s["id"])
        if "error" in info:
            continue
        chance = _incident_chance(info["total"])
        if chance <= 0:
            continue
        if rng.random() < chance:
            kind = _pick_incident(rng)
            triggered.append(_apply_incident(journal, s["id"], info, kind, rng))
    # Queue next roll regardless of outcomes.
    sid = schedule_next_roll(schedule_fn)
    return {"triggered": triggered, "next_roll_id": sid}
