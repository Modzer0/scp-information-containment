from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from .clock import iso, now_utc
from .journal import Journal


_TS = float(os.environ.get("SCP_TIME_SCALE", "1.0"))


def _d(seconds: float) -> float:
    return seconds * _TS


@dataclass(frozen=True)
class SiteType:
    type_id: str
    name: str
    capex_usd: int
    lead_time_s: float
    power_kw: int
    cooling_kw: int
    default_network: str
    requires_diesel: bool
    requires_pumps: bool = False
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "type_id": self.type_id,
            "name": self.name,
            "capex_usd": self.capex_usd,
            "lead_time_s": self.lead_time_s,
            "power_kw": self.power_kw,
            "cooling_kw": self.cooling_kw,
            "default_network": self.default_network,
            "requires_diesel": self.requires_diesel,
            "requires_pumps": self.requires_pumps,
            "description": self.description,
        }


TYPES: dict[str, SiteType] = {}


def _add(t: SiteType) -> None:
    TYPES[t.type_id] = t


_add(SiteType(
    "tent", "Temporary tent / field outpost",
    capex_usd=15_000, lead_time_s=_d(86_400 * 1),
    power_kw=2, cooling_kw=2,
    default_network="lte", requires_diesel=True,
    description="Canvas shelter + ARM kit. Days-to-weeks of tactical use.",
))
_add(SiteType(
    "office_closet", "Office rack closet",
    capex_usd=50_000, lead_time_s=_d(86_400 * 3),
    power_kw=5, cooling_kw=5,
    default_network="dsl", requires_diesel=False,
    description="Stealthy but density-limited. Grid-powered office rack.",
))
_add(SiteType(
    "bunker_shallow", "Shallow bunker (reinforced basement)",
    capex_usd=8_000_000, lead_time_s=_d(86_400 * 60),
    power_kw=40, cooling_kw=30,
    default_network="business_fiber", requires_diesel=False,
    description="Partial EM shielding + blast resistance. No active pumping needed.",
))
_add(SiteType(
    "onprem_dc", "On-premises data center",
    capex_usd=5_000_000, lead_time_s=_d(86_400 * 30),
    power_kw=200, cooling_kw=200,
    default_network="business_fiber", requires_diesel=False,
    description="Full-control DC. High capex, high capacity.",
))
_add(SiteType(
    "mobidc", "Containerized MobiDC (20-ft)",
    capex_usd=2_000_000, lead_time_s=_d(86_400 * 14),
    power_kw=50, cooling_kw=50,
    default_network="starstream", requires_diesel=True,
    description="Shippable DC in a 20-ft container. Runs on diesel genset.",
))
_add(SiteType(
    "field_site", "Field deployment kit",
    capex_usd=200_000, lead_time_s=_d(86_400 * 5),
    power_kw=10, cooling_kw=10,
    default_network="lte", requires_diesel=True,
    description="Portable compute + power kit. Solar / diesel hybrid.",
))
_add(SiteType(
    "subsea_pod", "Panthalassa-class subsea pod",
    capex_usd=80_000_000, lead_time_s=_d(86_400 * 60),
    power_kw=30, cooling_kw=300,      # seawater cooling — near unlimited
    default_network="geo_sat", requires_diesel=False,
    description="Seafloor compute pod. OTEC-powered; satellite-only comms.",
))
_add(SiteType(
    "underground", "Deep underground hardened base",
    capex_usd=200_000_000, lead_time_s=_d(86_400 * 180),
    power_kw=100, cooling_kw=60,      # ground-loop, limited
    default_network="business_fiber", requires_diesel=False,
    requires_pumps=True,
    description=(
        "Excavated deep bunker. Strong EM/memetic shielding + blast protection. "
        "Requires continuous dewatering pumps — without them the site floods."
    ),
))
_add(SiteType(
    "antarctica", "Antarctic research station",
    capex_usd=150_000_000, lead_time_s=_d(86_400 * 365),
    power_kw=50, cooling_kw=500,      # passive ambient
    default_network="geo_sat", requires_diesel=True,
    description="Polar ice station. Free passive cooling; brutal logistics.",
))
_add(SiteType(
    "oil_platform", "Offshore oil-platform conversion",
    capex_usd=45_000_000, lead_time_s=_d(86_400 * 180),
    power_kw=80, cooling_kw=400,      # seawater cooling
    default_network="starstream", requires_diesel=True,
    description=(
        "Repurposed decommissioned oil rig. Helipad + vessel moorage; "
        "international-waters-ish. Seawater cooling; helicopter logistics."
    ),
))


def list_types() -> list[SiteType]:
    return sorted(TYPES.values(), key=lambda t: t.capex_usd)


def get_type(type_id: str) -> SiteType | None:
    return TYPES.get(type_id)


# --- establishment pipeline -------------------------------------------


def establish_site(
    journal: Journal, schedule_fn: Any, type_id: str, name: str
) -> dict:
    st = get_type(type_id)
    if st is None:
        raise ValueError(f"unknown site type: {type_id}")

    current = journal.get_funding()
    if current < st.capex_usd:
        raise ValueError(
            f"insufficient funding: ${current:,} < ${st.capex_usd:,}"
        )

    balance = journal.adjust_funding(-st.capex_usd)
    eta = now_utc() + timedelta(seconds=st.lead_time_s)
    sid = schedule_fn(
        eta,
        "site_established",
        {"type_id": type_id, "name": name},
    )
    journal.append(
        "site_establishment_ordered",
        "INFO",
        {
            "type_id": type_id,
            "name": name,
            "capex": st.capex_usd,
            "balance": balance,
            "eta": iso(eta),
            "scheduled_id": sid,
        },
    )
    return {
        "type_id": type_id,
        "name": name,
        "eta": iso(eta),
        "balance": balance,
        "scheduled_id": sid,
    }


def on_site_established(
    journal: Journal, type_id: str, name: str
) -> dict:
    st = get_type(type_id)
    if st is None:
        return {"error": f"unknown site type: {type_id}"}

    site_id = journal.create_site(name, type_id)
    journal.set_site_capacity(site_id, power_kw=st.power_kw, cooling_kw=st.cooling_kw)
    journal.set_site_network(site_id, st.default_network)
    # New sites ship unencrypted — player must install encryption before
    # doing anything sensitive on them.
    journal.set_site_encryption(site_id, "none")
    # Pump-required sites need dewatering from day 1 or they flood. The
    # construction cost includes a starter small pump so the site isn't
    # dead on arrival; upgrade to redundant pumps for reliability.
    if st.requires_pumps:
        journal.create_pump(
            site_id=site_id, sku="pump-system-sm",
            capacity="small", redundant=False,
        )
    result = {
        "site_id": site_id,
        "type_id": type_id,
        "name": name,
        "power_kw": st.power_kw,
        "cooling_kw": st.cooling_kw,
        "default_network": st.default_network,
        "requires_diesel": st.requires_diesel,
    }
    journal.append("site_established", "INFO", result)
    return result


def site_requires_diesel(journal: Journal, site_id: int) -> bool:
    sites = journal.list_sites()
    match = next((s for s in sites if s["id"] == site_id), None)
    if not match:
        return False
    st = get_type(match["type"])
    return bool(st and st.requires_diesel)


def site_requires_pumps(journal: Journal, site_id: int) -> bool:
    sites = journal.list_sites()
    match = next((s for s in sites if s["id"] == site_id), None)
    if not match:
        return False
    st = get_type(match["type"])
    return bool(st and st.requires_pumps)
