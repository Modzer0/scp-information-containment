from __future__ import annotations

import os
import random
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from .clock import iso, now_utc
from .journal import Journal


_TS = float(os.environ.get("SCP_TIME_SCALE", "1.0"))


def _d(seconds: float) -> float:
    return seconds * _TS


@dataclass(frozen=True)
class Role:
    role_id: str
    display_name: str
    recruit_cost_usd: int          # one-time signing / relocation / agency fee
    annual_salary_usd: int         # gross annual — prorated weekly on payroll
    lead_time_s: float             # time to source + onboard
    skills: dict                   # starter skill levels
    clearance: int
    description: str

    def to_dict(self) -> dict:
        return {
            "role_id": self.role_id,
            "display_name": self.display_name,
            "recruit_cost_usd": self.recruit_cost_usd,
            "annual_salary_usd": self.annual_salary_usd,
            "lead_time_s": self.lead_time_s,
            "skills": self.skills,
            "clearance": self.clearance,
            "description": self.description,
        }


ROLES: dict[str, Role] = {}


def _add(r: Role) -> None:
    ROLES[r.role_id] = r


_add(Role(
    "analyst", "Analyst",
    recruit_cost_usd=50_000, annual_salary_usd=120_000,
    lead_time_s=_d(86_400 * 30),
    skills={"infosec": 20, "memetics": 5, "forensics": 10},
    clearance=1,
    description="Generalist infohazard analyst. Safe-class handling from day one.",
))
_add(Role(
    "sysadmin", "Systems administrator",
    recruit_cost_usd=60_000, annual_salary_usd=130_000,
    lead_time_s=_d(86_400 * 30),
    skills={"sysadmin": 30, "infosec": 15, "networking": 20},
    clearance=1,
    description="Keeps the infrastructure running. Good for mid-size sites.",
))
_add(Role(
    "forensics_tech", "Forensics technician",
    recruit_cost_usd=40_000, annual_salary_usd=90_000,
    lead_time_s=_d(86_400 * 21),
    skills={"forensics": 25, "infosec": 10},
    clearance=1,
    description="Handles wipe/reimage and chain-of-custody procedures.",
))
_add(Role(
    "memeticist_jr", "Memeticist (junior)",
    recruit_cost_usd=80_000, annual_salary_usd=160_000,
    lead_time_s=_d(86_400 * 45),
    skills={"memetics": 25, "infosec": 15},
    clearance=2,
    description="Euclid-class handler. Understands memetic hazards.",
))
_add(Role(
    "memeticist_sr", "Memeticist (senior)",
    recruit_cost_usd=150_000, annual_salary_usd=220_000,
    lead_time_s=_d(86_400 * 90),
    skills={"memetics": 50, "infosec": 30, "forensics": 15},
    clearance=3,
    description="Keter-certified. Rare, expensive, essential for high-class work.",
))
_add(Role(
    "reactor_operator", "Licensed reactor operator",
    recruit_cost_usd=200_000, annual_salary_usd=250_000,
    lead_time_s=_d(86_400 * 120),
    skills={"reactor_operator": 40, "power_systems": 30},
    clearance=2,
    description=(
        "NRC-style licensed operator. Required to commission SMRs / "
        "microreactors / MSRs. Long sourcing lead due to rare certification."
    ),
))
_add(Role(
    "pilot_fixed_wing", "Pilot (fixed-wing)",
    recruit_cost_usd=75_000, annual_salary_usd=150_000,
    lead_time_s=_d(86_400 * 45),
    skills={"fixed_wing_pilot": 40, "ifr_rated": 30, "multi_engine": 20},
    clearance=1,
    description="Commercial fixed-wing pilot. Adds to your aviation crew pool.",
))
_add(Role(
    "pilot_rotary", "Pilot (rotary-wing)",
    recruit_cost_usd=75_000, annual_salary_usd=150_000,
    lead_time_s=_d(86_400 * 45),
    skills={"rotary_pilot": 40, "ifr_rated": 25},
    clearance=1,
    description="Helicopter pilot. Tactical insertion + offshore work.",
))
_add(Role(
    "field_agent", "Field agent",
    recruit_cost_usd=50_000, annual_salary_usd=110_000,
    lead_time_s=_d(86_400 * 60),
    skills={"field_ops": 30, "infosec": 15},
    clearance=2,
    description="Goes to sites. Requires field cert before deployment.",
))
_add(Role(
    "scientist", "Research scientist",
    recruit_cost_usd=150_000, annual_salary_usd=200_000,
    lead_time_s=_d(86_400 * 60),
    skills={"research_methodology": 30, "memetics": 20},
    clearance=2,
    description="Lab research + publication. Required for R&D (future phase).",
))


def list_roles() -> list[Role]:
    return sorted(ROLES.values(), key=lambda r: r.recruit_cost_usd)


def get_role(role_id: str) -> Role | None:
    return ROLES.get(role_id)


# ---- procedural candidate names --------------------------------------

_FIRST = [
    "Alex", "Sam", "Jordan", "Casey", "Morgan", "Taylor", "Drew", "Reese",
    "Avery", "Rowan", "Quinn", "Blake", "Cameron", "Skyler", "Parker",
    "Harper", "Lane", "Kai", "Finley", "Emerson",
]
_LAST = [
    "Vey", "Osei", "Okafor", "Sato", "Reyes", "Karim", "Nakamura", "Dietrich",
    "Blackwood", "Ashworth", "Castellan", "Orlov", "Petrosyan", "Chen",
    "Ghosh", "Ferrera", "Hollis", "Lindqvist", "Mahmoud", "Singh",
    "Voss", "Whittaker", "Yamamoto", "Zaman", "Kowalski", "Laveau",
    "Moreau", "Novak", "Pemberton", "Quillen",
]


def generate_name(rng: random.Random) -> str:
    first = rng.choice(_FIRST)
    last = rng.choice(_LAST)
    # Titles are role-neutral — match Foundation convention (e.g. "Dr. Vey")
    title = rng.choice(["Dr.", "Dr.", "Ms.", "Mr.", ""]).strip()
    return f"{title} {first} {last}".strip()


# ---- lifecycle -------------------------------------------------------


def recruit(
    journal: Journal,
    schedule_fn: Any,
    role_id: str,
    rng: random.Random,
    target_site_id: int | None = None,
) -> dict:
    role = get_role(role_id)
    if role is None:
        raise ValueError(f"unknown role: {role_id}")

    sites = journal.list_sites()
    if not sites:
        raise ValueError("no sites available to assign hire to")
    if target_site_id is None:
        target_site_id = sites[0]["id"]
    elif not any(s["id"] == target_site_id for s in sites):
        raise ValueError(f"no site with id {target_site_id}")

    current = journal.get_funding()
    if current < role.recruit_cost_usd:
        raise ValueError(
            f"insufficient funding: ${current:,} < ${role.recruit_cost_usd:,}"
        )

    balance = journal.adjust_funding(-role.recruit_cost_usd)
    name = generate_name(rng)

    eta = now_utc() + timedelta(seconds=role.lead_time_s)
    sid = schedule_fn(
        eta,
        "hire_complete",
        {
            "role_id": role_id,
            "candidate_name": name,
            "target_site_id": target_site_id,
        },
    )
    journal.append(
        "recruitment_ordered",
        "INFO",
        {
            "role_id": role_id,
            "candidate_name": name,
            "recruit_cost": role.recruit_cost_usd,
            "balance": balance,
            "eta": iso(eta),
            "scheduled_id": sid,
        },
    )
    return {
        "scheduled_id": sid,
        "role_id": role_id,
        "candidate_name": name,
        "eta": iso(eta),
        "balance": balance,
        "target_site_id": target_site_id,
    }


def on_hire_complete(
    journal: Journal,
    role_id: str,
    candidate_name: str,
    target_site_id: int,
) -> dict:
    role = get_role(role_id)
    if role is None:
        return {"error": f"unknown role: {role_id}"}

    staff_id = journal.create_staff(
        name=candidate_name,
        role=role_id,
        is_player=False,
        skills=dict(role.skills),
        clearance=role.clearance,
        salary=role.annual_salary_usd,
        assigned_site_id=target_site_id,
    )
    result = {
        "staff_id": staff_id,
        "name": candidate_name,
        "role_id": role_id,
        "annual_salary": role.annual_salary_usd,
        "assigned_site_id": target_site_id,
    }
    journal.append("hire_complete", "INFO", result)
    return result
