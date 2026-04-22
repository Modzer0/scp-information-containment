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
class Course:
    course_id: str
    name: str
    duration_s: float           # pre-scaled by SCP_TIME_SCALE
    cost_usd: int
    skill: str
    skill_gain: int             # direct addition to skill (capped at 100)
    prereq_course_id: str | None = None
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "course_id": self.course_id,
            "name": self.name,
            "duration_s": self.duration_s,
            "cost_usd": self.cost_usd,
            "skill": self.skill,
            "skill_gain": self.skill_gain,
            "prereq_course_id": self.prereq_course_id,
            "description": self.description,
        }


COURSES: dict[str, Course] = {}


def _add(c: Course) -> None:
    COURSES[c.course_id] = c


_add(Course(
    "analyst_entry", "Analyst: Entry",
    duration_s=_d(2 * 3600), cost_usd=5_000,
    skill="infosec", skill_gain=10,
    description="Baseline infosec + pre-analysis checklist training.",
))
_add(Course(
    "forensics_l1", "Forensics: Level 1",
    duration_s=_d(4 * 3600), cost_usd=8_000,
    skill="forensics", skill_gain=15,
    description="Evidence preservation, wipe procedure, chain-of-custody.",
))
_add(Course(
    "memeticist_l1", "Memeticist: Level 1",
    duration_s=_d(8 * 3600), cost_usd=20_000,
    skill="memetics", skill_gain=15,
    prereq_course_id="analyst_entry",
    description="Identifying memetic payloads and mnestic protocols.",
))
_add(Course(
    "infosec_advanced", "Infosec: Advanced",
    duration_s=_d(2 * 86_400), cost_usd=25_000,
    skill="infosec", skill_gain=20,
    prereq_course_id="analyst_entry",
    description="Advanced containment, VM hygiene, and procedure design.",
))
_add(Course(
    "memeticist_l3", "Memeticist: Level 3",
    duration_s=_d(3 * 86_400), cost_usd=50_000,
    skill="memetics", skill_gain=20,
    prereq_course_id="memeticist_l1",
    description="Keter-class handling authorisation. Required for Level-3 ops.",
))
_add(Course(
    "reactor_operator", "Licensed reactor operator",
    duration_s=_d(6 * 7 * 86_400), cost_usd=120_000,
    skill="reactor_operator", skill_gain=30,
    description=(
        "Six-week licensing course. Required staff to operate micro-reactors + "
        "SMRs (purchasable as power_plant SKUs). Plan headcount before ordering."
    ),
))


def list_courses() -> list[Course]:
    return sorted(COURSES.values(), key=lambda c: (c.prereq_course_id or "", c.duration_s))


def get(course_id: str) -> Course | None:
    return COURSES.get(course_id)


def enroll(
    journal: Journal,
    schedule_fn: Any,
    staff_id: int,
    course_id: str,
) -> dict:
    course = get(course_id)
    if not course:
        raise ValueError(f"unknown course: {course_id}")

    staff = journal.get_staff(staff_id)
    if not staff:
        raise ValueError(f"no staff {staff_id}")
    if staff["status"] != "active":
        raise ValueError(f"staff {staff_id} is {staff['status']}, not active")

    # Already trained?
    if journal.has_completed_course(staff_id, course_id):
        raise ValueError(f"{staff['name']} already completed {course_id}")

    # Already enrolled in something?
    active_enrollments = journal.list_enrollments(
        staff_id=staff_id, status="enrolled"
    )
    if active_enrollments:
        raise ValueError(
            f"{staff['name']} already enrolled in {active_enrollments[0]['course_id']}"
        )

    # Prereq check
    if course.prereq_course_id and not journal.has_completed_course(
        staff_id, course.prereq_course_id
    ):
        raise ValueError(
            f"prereq not met: {course.prereq_course_id} required before {course_id}"
        )

    # Funding check
    current = journal.get_funding()
    if current < course.cost_usd:
        raise ValueError(
            f"insufficient funding: ${current:,} < ${course.cost_usd:,}"
        )

    new_balance = journal.adjust_funding(-course.cost_usd)
    journal.set_staff_status(staff_id, "training")

    eta = now_utc() + timedelta(seconds=course.duration_s)
    enrollment_id = journal.create_enrollment(staff_id, course_id, eta)
    sid = schedule_fn(
        eta, "training_complete", {"enrollment_id": enrollment_id}
    )
    journal.append(
        "enrollment_started",
        "INFO",
        {
            "enrollment_id": enrollment_id,
            "staff_id": staff_id,
            "staff_name": staff["name"],
            "course_id": course_id,
            "cost_usd": course.cost_usd,
            "balance": new_balance,
            "eta": iso(eta),
        },
    )
    return {
        "enrollment_id": enrollment_id,
        "scheduled_id": sid,
        "eta": iso(eta),
        "staff_name": staff["name"],
        "course": course.name,
        "balance": new_balance,
    }


def on_training_complete(journal: Journal, enrollment_id: int) -> dict:
    enr = journal.get_enrollment(enrollment_id)
    if not enr:
        return {"error": f"no enrollment {enrollment_id}"}
    course = get(enr["course_id"])
    if not course:
        return {"error": f"unknown course {enr['course_id']}"}

    before, after = journal.add_skill_direct(
        enr["staff_id"], course.skill, course.skill_gain
    )
    journal.set_staff_status(enr["staff_id"], "active")
    journal.mark_enrollment_graduated(enrollment_id)

    staff = journal.get_staff(enr["staff_id"]) or {}
    result = {
        "enrollment_id": enrollment_id,
        "staff_id": enr["staff_id"],
        "staff_name": staff.get("name", ""),
        "course_id": enr["course_id"],
        "skill": course.skill,
        "before": before,
        "after": after,
        "gain": after - before,
    }
    journal.append("training_complete", "INFO", result)
    return result
