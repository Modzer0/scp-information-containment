"""
Rival-GOI intel groundwork — DESIGN §24.6 foundation.

This module lays the data model and dispatch plumbing for detecting
rival Groups of Interest (GOIs) with SIGINT / ELINT / IMINT / HUMINT
missions. The player starts with no knowledge of rival sites; as
missions succeed, contacts advance through states:

    (unknown, no row)
      → rumored     — we know something exists in region X
      → located     — we know site type + GOI identity
      → cataloged   — full capability readout; mission-planning ready

Groundwork scope: rival catalog, per-save contact state, mission
dispatch with scheduler-fired completion, detection rolls. Deferred
(DESIGN §24.5 / §24.6 full): retaliation against the player, rival
GOI dynamic behavior, the raid pipeline itself.
"""
from __future__ import annotations

import json
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


# --- Regions ---------------------------------------------------------

REGIONS: tuple[str, ...] = (
    "north_america",
    "south_america",
    "europe",
    "africa",
    "middle_east",
    "south_asia",
    "east_asia",
    "oceania",
    "arctic",
    "antarctic",
    "atlantic",
    "pacific",
    "indian_ocean",
    "space",            # orbital assets / LEO dead zones
)


def is_valid_region(r: str) -> bool:
    return r in REGIONS


# --- Rival GOIs + sites (catalog, hardcoded) -------------------------


@dataclass(frozen=True)
class RivalGoi:
    goi_id: str
    name: str
    disposition: str         # "hostile" | "competitor" | "state" | "criminal"
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "goi_id": self.goi_id,
            "name": self.name,
            "disposition": self.disposition,
            "description": self.description,
        }


@dataclass(frozen=True)
class RivalSiteTemplate:
    template_id: str
    goi_id: str
    name: str
    site_type: str           # rival_bunker | corporate_hq | state_facility | black_site | sea_platform
    region: str
    stealth: int             # 0–100; detection rolls compare against this
    capability_summary: str = ""

    def to_dict(self) -> dict:
        return {
            "template_id": self.template_id,
            "goi_id": self.goi_id,
            "name": self.name,
            "site_type": self.site_type,
            "region": self.region,
            "stealth": self.stealth,
            "capability_summary": self.capability_summary,
        }


GOIS: dict[str, RivalGoi] = {}


def _gadd(g: RivalGoi) -> None:
    GOIS[g.goi_id] = g


_gadd(RivalGoi(
    "chaos_insurgency", "Chaos Insurgency",
    disposition="hostile",
    description=(
        "Splinter faction; steals SCPs for weaponization. High-stealth "
        "black sites and mobile cells."
    ),
))
_gadd(RivalGoi(
    "marshall_carter_dark", "Marshall, Carter & Dark Ltd.",
    disposition="competitor",
    description=(
        "Corporate anomaly broker. Runs legal-front offices plus "
        "invitation-only auction houses."
    ),
))
_gadd(RivalGoi(
    "goc", "Global Occult Coalition",
    disposition="state",
    description=(
        "State-coalition rival. Destroys rather than contains; hostile "
        "when our cover slips."
    ),
))
_gadd(RivalGoi(
    "prometheus_labs", "Prometheus Labs",
    disposition="competitor",
    description=(
        "Corporate anomalous-tech developer. Nominally defunct, but "
        "active subsidiaries persist."
    ),
))
_gadd(RivalGoi(
    "church_broken_god", "Church of the Broken God",
    disposition="hostile",
    description=(
        "Mechanical-cult cells. Fewer sites but long-horizon infiltration "
        "of critical infrastructure."
    ),
))


SITE_TEMPLATES: list[RivalSiteTemplate] = [
    # Chaos Insurgency
    RivalSiteTemplate("ci_alpha_urals", "chaos_insurgency",
                      "CI Alpha Site (Urals)", "rival_bunker",
                      "europe", stealth=75,
                      capability_summary="Bunker; est. Safe/Euclid cache, air defenses."),
    RivalSiteTemplate("ci_delta_gulf", "chaos_insurgency",
                      "CI Delta Cell (Gulf of Mexico)", "sea_platform",
                      "atlantic", stealth=70,
                      capability_summary="Repurposed rig; small-arms escort."),
    RivalSiteTemplate("ci_theta_patagonia", "chaos_insurgency",
                      "CI Theta Compound", "black_site",
                      "south_america", stealth=80,
                      capability_summary="Remote compound; ground-assault needed."),
    # Marshall, Carter & Dark
    RivalSiteTemplate("mcd_london_hq", "marshall_carter_dark",
                      "M.C.&D. London Office", "corporate_hq",
                      "europe", stealth=40,
                      capability_summary="Corporate cover; paper trail exploitable."),
    RivalSiteTemplate("mcd_dubai_vault", "marshall_carter_dark",
                      "M.C.&D. Dubai Vault", "corporate_hq",
                      "middle_east", stealth=55,
                      capability_summary="Auction vault; invitation-gated."),
    RivalSiteTemplate("mcd_kowloon_black", "marshall_carter_dark",
                      "M.C.&D. Kowloon Black Market", "black_site",
                      "east_asia", stealth=65,
                      capability_summary="Illicit anomaly trade hub."),
    # GOC
    RivalSiteTemplate("goc_geneva_hq", "goc",
                      "GOC Geneva Council", "state_facility",
                      "europe", stealth=50,
                      capability_summary="Policy HQ; public-facing facade."),
    RivalSiteTemplate("goc_djibouti_fob", "goc",
                      "GOC Djibouti FOB", "state_facility",
                      "africa", stealth=60,
                      capability_summary="Forward strike base; PMSC-heavy."),
    RivalSiteTemplate("goc_mcmurdo_obs", "goc",
                      "GOC McMurdo Watch Post", "state_facility",
                      "antarctic", stealth=65,
                      capability_summary="Long-range sensor array."),
    # Prometheus Labs
    RivalSiteTemplate("prom_siegen_lab", "prometheus_labs",
                      "Prometheus Siegen Lab", "corporate_hq",
                      "europe", stealth=60,
                      capability_summary="R&D campus; nominal shutdown cover."),
    RivalSiteTemplate("prom_pyongyang_joint", "prometheus_labs",
                      "Prometheus Pyongyang JV", "state_facility",
                      "east_asia", stealth=70,
                      capability_summary="State-JV anomaly lab."),
    # Church of the Broken God
    RivalSiteTemplate("cbg_venice_chapel", "church_broken_god",
                      "CBG Venice Chapel", "cult_cell",
                      "europe", stealth=55,
                      capability_summary="Mechanical-cult temple."),
    RivalSiteTemplate("cbg_detroit_auto", "church_broken_god",
                      "CBG Detroit Auto Works", "cult_cell",
                      "north_america", stealth=60,
                      capability_summary="Industrial front; heavy machinery."),
]


def list_gois() -> list[RivalGoi]:
    return sorted(GOIS.values(), key=lambda g: g.goi_id)


def get_goi(goi_id: str) -> RivalGoi | None:
    return GOIS.get(goi_id)


def list_site_templates() -> list[RivalSiteTemplate]:
    return list(SITE_TEMPLATES)


def get_site_template(template_id: str) -> RivalSiteTemplate | None:
    return next((t for t in SITE_TEMPLATES if t.template_id == template_id), None)


def seed_rivals_if_empty(journal: Journal) -> int:
    """Populate the rival_sites table on first boot. Returns count seeded."""
    if journal.count_rival_sites() > 0:
        return 0
    n = 0
    for t in SITE_TEMPLATES:
        journal.create_rival_site(
            template_id=t.template_id,
            goi_id=t.goi_id,
            name=t.name,
            site_type=t.site_type,
            region=t.region,
            stealth=t.stealth,
            capability_summary=t.capability_summary,
        )
        n += 1
    journal.append(
        "rivals_seeded", "INFO",
        {"count": n, "gois": [g.goi_id for g in list_gois()]},
    )
    return n


# --- Intel contacts --------------------------------------------------
#
# A contact row represents what the PLAYER knows about a rival site.
# Absence of a row = "unknown". Successive mission hits advance the
# state. We never downgrade — losing intel is a future mechanic.

CONTACT_STATES: tuple[str, ...] = ("unknown", "rumored", "located", "cataloged")


def _next_contact_state(current: str) -> str:
    try:
        idx = CONTACT_STATES.index(current)
    except ValueError:
        idx = 0
    return CONTACT_STATES[min(idx + 1, len(CONTACT_STATES) - 1)]


# --- Mission kinds + dispatch ---------------------------------------


MISSION_KINDS: tuple[str, ...] = ("sigint", "elint", "imint", "humint")

# Base duration in game-seconds per mission (pre-scaled by SCP_TIME_SCALE).
_MISSION_DURATIONS = {
    "sigint": _d(12 * 3600),
    "elint":  _d(12 * 3600),
    "imint":  _d(6 * 3600),
    "humint": _d(48 * 3600),
}

# Baseline asset detection power when a matching asset is supplied.
_KIND_BASE_POWER = {
    "sigint": 45,
    "elint":  50,
    "imint":  55,
    "humint": 60,
}


def _aircraft_bonus(journal: Journal, aircraft_id: int, kind: str) -> int:
    from .hardware import catalog as hw
    rows = [a for a in journal.list_aircraft() if a["id"] == aircraft_id]
    if not rows:
        return 0
    sku = hw.get(rows[0].get("sku", ""))
    if sku is None:
        return 0
    isr = str(sku.capabilities.get("isr_type", ""))
    # Match isr_type to mission kind
    if kind == "sigint" and isr in ("sigint", "sigint_elint"):
        return 20
    if kind == "elint" and isr in ("sigint_elint", "radar"):
        return 20
    if kind == "imint" and isr in ("imint", "gmti", "radar"):
        return 20
    return 0


def _vessel_bonus(journal: Journal, vessel_type: str, vessel_id: int, kind: str) -> int:
    from . import vessel_ops as _vo
    eqs = journal.list_vessel_equipment(vessel_type, vessel_id)
    bonus = 0
    for eq in eqs:
        e = _vo.get_equipment(eq["sku"])
        if e is None:
            continue
        if e.category == "sensor":
            # General sensor utility
            bonus += min(e.rating, 10)
            # ELINT suite boosts elint missions extra
            if kind == "elint" and "elint" in e.sku:
                bonus += 10
            # Active sonar / hydrophone help imint/sigint less — leave flat
        if e.category == "comm" and kind == "sigint":
            bonus += 5
    return min(bonus, 40)


def _satellite_bonus(journal: Journal, satellite_id: int, kind: str) -> int:
    sats = [s for s in journal.list_satellites() if s["id"] == satellite_id]
    if not sats or sats[0].get("status") != "on_orbit":
        return 0
    payload = str(sats[0].get("payload", ""))
    if kind == "sigint" and payload == "sigint":
        return 25
    if kind == "imint" and payload == "imint":
        return 30
    return 0


def _staff_bonus(journal: Journal, staff_id: int, kind: str) -> int:
    s = journal.get_staff(staff_id)
    if not s:
        return 0
    if s.get("status") != "active":
        return 0
    skills = s.get("skills", {}) or {}
    info = int(skills.get("infosec", 0))
    if kind == "humint":
        return max(0, info - 30)     # 0 below infosec 30; 40 at infosec 70
    return 0


def _site_security_bonus(journal: Journal, site_id: int | None, kind: str) -> int:
    """Fixed-site signals gear (IMINT dome / COMINT mast / ELINT array)
    bumps collection when the mission launches from a home site that
    has them installed."""
    if site_id is None:
        return 0
    try:
        rows = journal.list_site_security(int(site_id))
    except Exception:
        return 0
    bonus = 0
    for r in rows:
        sku = r.get("sku", "")
        if kind == "imint" and sku == "imint-dome":
            bonus += 15
        elif kind == "sigint" and sku == "comint-mast":
            bonus += 15
        elif kind == "elint" and sku == "elint-array":
            bonus += 20
    return min(bonus, 40)


def estimate_power(
    journal: Journal,
    kind: str,
    asset_type: str | None,
    asset_id: int | None,
    home_site_id: int | None,
) -> dict:
    """Expose the power breakdown before dispatch so the TUI can show a
    cost/benefit preview."""
    if kind not in MISSION_KINDS:
        raise ValueError(f"unknown mission kind: {kind}")
    base = _KIND_BASE_POWER[kind]
    asset_bonus = 0
    if asset_type == "aircraft" and asset_id is not None:
        asset_bonus = _aircraft_bonus(journal, int(asset_id), kind)
    elif asset_type in ("ship", "submarine") and asset_id is not None:
        asset_bonus = _vessel_bonus(journal, asset_type, int(asset_id), kind)
    elif asset_type == "satellite" and asset_id is not None:
        asset_bonus = _satellite_bonus(journal, int(asset_id), kind)
    elif asset_type == "staff" and asset_id is not None:
        asset_bonus = _staff_bonus(journal, int(asset_id), kind)
    site_bonus = _site_security_bonus(journal, home_site_id, kind)
    return {
        "kind": kind,
        "base": base,
        "asset_bonus": asset_bonus,
        "site_bonus": site_bonus,
        "total": base + asset_bonus + site_bonus,
    }


# --- Dispatch + completion -------------------------------------------


def dispatch_mission(
    journal: Journal,
    schedule_fn: Any,
    kind: str,
    region: str,
    asset_type: str | None = None,
    asset_id: int | None = None,
    home_site_id: int | None = None,
) -> dict:
    """Start an intel mission. Returns the mission row + eta + power estimate."""
    if kind not in MISSION_KINDS:
        raise ValueError(
            f"unknown mission kind '{kind}'; valid: {', '.join(MISSION_KINDS)}"
        )
    if not is_valid_region(region):
        raise ValueError(
            f"unknown region '{region}'; valid: {', '.join(REGIONS)}"
        )
    # Soft validation — asset must exist if named
    if asset_type and asset_id is not None:
        if asset_type == "aircraft":
            if not any(a["id"] == asset_id for a in journal.list_aircraft()):
                raise ValueError(f"no aircraft {asset_id}")
        elif asset_type == "ship":
            if not any(s["id"] == asset_id for s in journal.list_ships()):
                raise ValueError(f"no ship {asset_id}")
        elif asset_type == "submarine":
            if not any(s["id"] == asset_id for s in journal.list_submarines()):
                raise ValueError(f"no submarine {asset_id}")
        elif asset_type == "satellite":
            if not any(s["id"] == asset_id for s in journal.list_satellites()):
                raise ValueError(f"no satellite {asset_id}")
        elif asset_type == "staff":
            if journal.get_staff(int(asset_id)) is None:
                raise ValueError(f"no staff {asset_id}")
        else:
            raise ValueError(f"unknown asset_type '{asset_type}'")

    # HUMINT requires an asset (staff operative). Others can go asset-less
    # but their effectiveness drops to base only.
    if kind == "humint" and (asset_type != "staff" or asset_id is None):
        raise ValueError("humint requires asset_type='staff' + asset_id")

    power = estimate_power(journal, kind, asset_type, asset_id, home_site_id)

    duration_s = _MISSION_DURATIONS[kind]
    eta = now_utc() + timedelta(seconds=duration_s)

    mission_id = journal.create_intel_mission(
        kind=kind,
        region=region,
        asset_type=asset_type or "",
        asset_id=int(asset_id) if asset_id is not None else None,
        home_site_id=int(home_site_id) if home_site_id is not None else None,
        eta_iso=iso(eta),
        power=power["total"],
    )
    sid = schedule_fn(eta, "intel_mission_complete", {"mission_id": mission_id})
    journal.set_intel_mission_scheduled_id(mission_id, int(sid))

    # Tag the asset as busy on a mission so the TUI can show state
    if asset_type in ("ship", "submarine") and asset_id is not None:
        # Leave vessel status alone — intel-only missions don't conflict with
        # a concurrent patrol order today. This is a conservative choice the
        # §24.6 expansion can tighten.
        pass

    journal.append(
        "intel_mission_dispatched",
        "INFO",
        {
            "mission_id": mission_id,
            "kind": kind,
            "region": region,
            "asset_type": asset_type,
            "asset_id": asset_id,
            "power": power["total"],
            "power_breakdown": power,
            "eta": iso(eta),
            "scheduled_id": sid,
        },
    )
    return {
        "mission_id": mission_id,
        "kind": kind,
        "region": region,
        "asset_type": asset_type,
        "asset_id": asset_id,
        "eta": iso(eta),
        "power": power,
        "scheduled_id": sid,
    }


def _detection_chance_pct(power: int, stealth: int) -> int:
    """Linear map of (power - stealth) offset by +50; clamped [5, 95]."""
    raw = power - stealth + 50
    if raw < 5:
        return 5
    if raw > 95:
        return 95
    return int(raw)


def on_mission_complete(
    journal: Journal, mission_id: int, rng: random.Random | None = None
) -> dict:
    m = journal.get_intel_mission(int(mission_id))
    if m is None:
        return {"error": f"no mission {mission_id}"}
    if m["state"] != "active":
        return {"mission_id": mission_id, "state": m["state"]}

    rng = rng or random.Random()
    region = m["region"]
    kind = m["kind"]
    power = int(m["power"])

    # Roll against every rival site in the mission region. Each roll is
    # independent; a sweep can light up multiple contacts.
    targets = [
        s for s in journal.list_rival_sites()
        if s["region"] == region
    ]
    upgrades: list[dict] = []
    for site in targets:
        chance = _detection_chance_pct(power, int(site["stealth"]))
        roll = rng.randint(1, 100)
        if roll > chance:
            continue
        # Success: advance contact state
        current = journal.get_intel_contact_state(int(site["id"]))
        new_state = _next_contact_state(current or "unknown")
        if new_state == current:
            continue   # already maxed
        journal.upsert_intel_contact(
            rival_site_id=int(site["id"]),
            state=new_state,
            details_json=json.dumps({"last_kind": kind, "last_power": power}),
        )
        upgrades.append({
            "rival_site_id": site["id"],
            "rival_name": site["name"],
            "goi_id": site["goi_id"],
            "before": current or "unknown",
            "after": new_state,
            "chance": chance,
            "roll": roll,
        })

    result = {
        "mission_id": mission_id,
        "kind": kind,
        "region": region,
        "power": power,
        "targets_in_region": len(targets),
        "upgrades": upgrades,
    }
    journal.set_intel_mission_state(
        int(mission_id), "complete", json.dumps(result)
    )
    sev = "NOTICE" if upgrades else "INFO"
    journal.append("intel_mission_complete", sev, result)
    return result
