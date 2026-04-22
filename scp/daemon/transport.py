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
class TransportMethod:
    method_id: str
    name: str
    duration_s: float      # pre-scaled
    cost_per_move: int
    description: str

    def to_dict(self) -> dict:
        return {
            "method_id": self.method_id,
            "name": self.name,
            "duration_s": self.duration_s,
            "cost_per_move": self.cost_per_move,
            "description": self.description,
        }


METHODS: dict[str, TransportMethod] = {}


def _add(m: TransportMethod) -> None:
    METHODS[m.method_id] = m


_add(TransportMethod(
    "truck", "Cargo truck",
    duration_s=_d(6 * 3600),
    cost_per_move=5_000,
    description="Overland cargo. Slow and cheap. Visible to roadside intel.",
))
_add(TransportMethod(
    "air", "Air cargo charter",
    duration_s=_d(2 * 3600),
    cost_per_move=25_000,
    description="Fast. Appears in commercial flight records.",
))
_add(TransportMethod(
    "rail", "Rail freight",
    duration_s=_d(12 * 3600),
    cost_per_move=3_000,
    description="Bulk overland. Slow, cheapest per move, fixed routes.",
))
_add(TransportMethod(
    "sea", "Sea freight",
    duration_s=_d(48 * 3600),
    cost_per_move=2_000,
    description="Cross-ocean bulk. Slowest, cheapest per move.",
))


def list_methods() -> list[TransportMethod]:
    return sorted(METHODS.values(), key=lambda m: m.duration_s)


def get_method(method_id: str) -> TransportMethod | None:
    return METHODS.get(method_id)


# --- item transfer ----------------------------------------------------


def transfer_item(
    journal: Journal,
    schedule_fn: Any,
    item_id: int,
    to_site_id: int,
    method_id: str = "truck",
) -> dict:
    method = get_method(method_id)
    if method is None:
        raise ValueError(f"unknown transport method: {method_id}")

    item = journal.get_item(item_id)
    if item is None:
        raise ValueError(f"no item {item_id}")
    if item["state"] != "archived":
        raise ValueError(
            f"item {item_id} is {item['state']}, must be archived to transfer"
        )

    from_site_id = item.get("current_site_id")
    if from_site_id is None:
        raise ValueError(f"item {item_id} has no known current site")

    if int(from_site_id) == int(to_site_id):
        raise ValueError(f"item {item_id} already at site {to_site_id}")

    # Validate destination site exists
    if not any(s["id"] == to_site_id for s in journal.list_sites()):
        raise ValueError(f"no site with id {to_site_id}")

    # Owned aircraft cuts the air-charter rate in half — you're using
    # your own hull instead of chartering a commercial flight. Same logic
    # for sea transport when you own a ship.
    effective_cost = method.cost_per_move
    owned_discount = False
    if method_id == "air" and journal.count_aircraft() > 0:
        effective_cost = method.cost_per_move // 2
        owned_discount = True
    elif method_id == "sea" and journal.count_ships() > 0:
        effective_cost = method.cost_per_move // 2
        owned_discount = True

    current = journal.get_funding()
    if current < effective_cost:
        raise ValueError(
            f"insufficient funding: ${current:,} < ${effective_cost:,}"
        )

    balance = journal.adjust_funding(-effective_cost)
    journal.set_item_state(item_id, "in_transit", current_vm_id=None)
    journal.set_item_transit(item_id, to_site_id)

    eta = now_utc() + timedelta(seconds=method.duration_s)
    sid = schedule_fn(
        eta,
        "transit_complete",
        {"item_id": item_id},
    )
    journal.append(
        "transit_started",
        "INFO",
        {
            "item_id": item_id,
            "from_site_id": from_site_id,
            "to_site_id": to_site_id,
            "method": method_id,
            "cost": effective_cost,
            "owned_discount": owned_discount,
            "balance": balance,
            "eta": iso(eta),
            "scheduled_id": sid,
        },
    )
    return {
        "item_id": item_id,
        "from_site_id": from_site_id,
        "to_site_id": to_site_id,
        "method": method_id,
        "cost": effective_cost,
        "owned_discount": owned_discount,
        "eta": iso(eta),
        "balance": balance,
        "scheduled_id": sid,
    }


def on_transit_complete(journal: Journal, item_id: int) -> dict:
    item = journal.get_item(item_id)
    if item is None:
        return {"error": f"no item {item_id}"}
    to_site = item.get("transit_to_site_id")
    if to_site is None:
        return {"error": f"item {item_id} has no transit destination"}

    from_site = item.get("current_site_id")
    journal.set_item_site(item_id, int(to_site))
    journal.set_item_transit(item_id, None)
    journal.set_item_state(item_id, "archived", current_vm_id=None)
    result = {
        "item_id": item_id,
        "designation": item["designation"],
        "from_site_id": from_site,
        "to_site_id": int(to_site),
    }
    journal.append("transit_complete", "INFO", result)
    return result


# --- host relocation --------------------------------------------------

# Cost multipliers by host class — bigger iron, harder to ship
HOST_CLASS_COST_MULT = {
    "server": 2.0,
    "aipod": 5.0,
    "mainframe": 10.0,
}


def relocate_host(
    journal: Journal,
    schedule_fn: Any,
    host_id: int,
    to_site_id: int,
    method_id: str = "truck",
) -> dict:
    method = get_method(method_id)
    if method is None:
        raise ValueError(f"unknown transport method: {method_id}")

    host = journal.get_host(host_id)
    if host is None:
        raise ValueError(f"no host {host_id}")
    if host["status"] != "clean":
        raise ValueError(
            f"host {host_id} is {host['status']}; only clean hosts can relocate"
        )
    if int(host["site_id"]) == int(to_site_id):
        raise ValueError(f"host {host_id} already at site {to_site_id}")
    if not any(s["id"] == to_site_id for s in journal.list_sites()):
        raise ValueError(f"no site with id {to_site_id}")

    # Block if any VM on this host is busy (in-flight analysis).
    vms = [v for v in journal.list_vms() if v["host_id"] == host_id]
    if any(v["status"] == "busy" for v in vms):
        raise ValueError(
            f"host {host_id} has busy VMs; complete analyses before moving"
        )

    host_class = host.get("class", "server")
    multiplier = HOST_CLASS_COST_MULT.get(host_class, 2.0)
    effective_cost = int(method.cost_per_move * multiplier)
    # Hosts take ~2x longer than small items (bigger, more fragile)
    duration_s = method.duration_s * 2

    if journal.get_funding() < effective_cost:
        raise ValueError(
            f"insufficient funding: ${journal.get_funding():,} < ${effective_cost:,}"
        )

    balance = journal.adjust_funding(-effective_cost)
    from_site_id = host["site_id"]

    journal.set_host_status(host_id, "in_transit")
    journal.set_host_transit(host_id, to_site_id)
    journal.set_vms_on_host_status(host_id, "offline")

    from datetime import timedelta as _td
    eta = now_utc() + _td(seconds=duration_s)
    sid = schedule_fn(eta, "host_arrived", {"host_id": host_id})
    journal.append(
        "host_relocation_started",
        "NOTICE",
        {
            "host_id": host_id,
            "from_site_id": from_site_id,
            "to_site_id": to_site_id,
            "method": method_id,
            "cost": effective_cost,
            "balance": balance,
            "eta": iso(eta),
            "scheduled_id": sid,
        },
    )
    return {
        "host_id": host_id,
        "from_site_id": from_site_id,
        "to_site_id": to_site_id,
        "method": method_id,
        "cost": effective_cost,
        "eta": iso(eta),
        "balance": balance,
        "scheduled_id": sid,
    }


def on_host_arrived(journal: Journal, host_id: int) -> dict:
    host = journal.get_host(host_id)
    if host is None:
        return {"error": f"no host {host_id}"}
    to_site = host.get("transit_to_site_id")
    if to_site is None:
        return {"error": f"host {host_id} has no transit destination"}

    from_site = host["site_id"]
    journal.set_host_site(host_id, int(to_site))
    journal.set_host_transit(host_id, None)
    journal.set_host_status(host_id, "clean")
    # VMs on this host return to idle (they were offline during transit).
    journal.set_vms_on_host_status(host_id, "idle")
    result = {
        "host_id": host_id,
        "name": host["name"],
        "from_site_id": from_site,
        "to_site_id": int(to_site),
    }
    journal.append("host_arrived", "INFO", result)
    return result


# --- staff reassignment -----------------------------------------------

STAFF_TRAVEL_DURATION_S = _d(6 * 3600)
STAFF_TRAVEL_COST = 1_000


def reassign_staff(
    journal: Journal,
    schedule_fn: Any,
    staff_id: int,
    to_site_id: int,
) -> dict:
    staff = journal.get_staff(staff_id)
    if staff is None:
        raise ValueError(f"no staff {staff_id}")
    if staff["status"] != "active":
        raise ValueError(
            f"{staff['name']} is {staff['status']}; only active staff can travel"
        )
    if staff.get("assigned_site_id") == to_site_id:
        raise ValueError(f"{staff['name']} already at site {to_site_id}")
    if not any(s["id"] == to_site_id for s in journal.list_sites()):
        raise ValueError(f"no site with id {to_site_id}")

    if journal.get_funding() < STAFF_TRAVEL_COST:
        raise ValueError(
            f"insufficient funding: ${journal.get_funding():,} < ${STAFF_TRAVEL_COST:,}"
        )

    balance = journal.adjust_funding(-STAFF_TRAVEL_COST)
    from_site_id = staff.get("assigned_site_id")
    journal.set_staff_status(staff_id, "traveling")
    journal.set_staff_transit(staff_id, to_site_id)

    from datetime import timedelta as _td
    eta = now_utc() + _td(seconds=STAFF_TRAVEL_DURATION_S)
    sid = schedule_fn(eta, "staff_arrived", {"staff_id": staff_id})
    journal.append(
        "staff_travel_started",
        "INFO",
        {
            "staff_id": staff_id,
            "staff_name": staff["name"],
            "from_site_id": from_site_id,
            "to_site_id": to_site_id,
            "cost": STAFF_TRAVEL_COST,
            "balance": balance,
            "eta": iso(eta),
            "scheduled_id": sid,
        },
    )
    return {
        "staff_id": staff_id,
        "staff_name": staff["name"],
        "from_site_id": from_site_id,
        "to_site_id": to_site_id,
        "cost": STAFF_TRAVEL_COST,
        "eta": iso(eta),
        "balance": balance,
        "scheduled_id": sid,
    }


def on_staff_arrived(journal: Journal, staff_id: int) -> dict:
    staff = journal.get_staff(staff_id)
    if staff is None:
        return {"error": f"no staff {staff_id}"}
    to_site = staff.get("transit_to_site_id")
    if to_site is None:
        return {"error": f"staff {staff_id} has no transit destination"}

    from_site = staff.get("assigned_site_id")
    journal.set_staff_assignment(staff_id, int(to_site))
    journal.set_staff_transit(staff_id, None)
    journal.set_staff_status(staff_id, "active")
    result = {
        "staff_id": staff_id,
        "staff_name": staff["name"],
        "from_site_id": from_site,
        "to_site_id": int(to_site),
    }
    journal.append("staff_arrived", "INFO", result)
    return result
