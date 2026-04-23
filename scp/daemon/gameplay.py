from __future__ import annotations

import os
import random
from datetime import timedelta
from typing import Any

import random as _random
from datetime import timedelta

from . import guardrail, incidents, mistakes, network, procurement
from .clock import now_utc
from .containment import VmSpec, leak_category, seed_vm_spec
from .content.items import generate as generate_item
from .journal import Journal


_LEAK_ORDER = ["stable", "slow_leak", "active_leak", "catastrophic"]


def _maybe_brownout(site_util: dict) -> tuple[bool, float]:
    """Return (brownout_hit, p_used). Probability scales with overload
    severity; capacity of 0 (lapsed grid) forces near-certain brownout."""
    if not site_util:
        return (False, 0.0)
    power_over = bool(site_util.get("power_over"))
    cooling_over = bool(site_util.get("cooling_over"))
    if not (power_over or cooling_over):
        return (False, 0.0)

    pcap = max(float(site_util.get("power_kw_capacity", 0)), 0.0)
    ccap = max(float(site_util.get("cooling_kw_capacity", 0)), 0.0)
    pused = float(site_util.get("power_kw_used", 0))
    cused = float(site_util.get("cooling_kw_used", 0))

    # If capacity is 0 and load is positive, treat as maximum severity.
    if (pcap == 0.0 and pused > 0.0) or (ccap == 0.0 and cused > 0.0):
        p = 0.9
    else:
        power_ratio = (pused / max(pcap, 0.001)) - 1.0 if power_over else 0.0
        cooling_ratio = (cused / max(ccap, 0.001)) - 1.0 if cooling_over else 0.0
        severity = max(power_ratio, cooling_ratio)
        p = min(max(severity * 0.3, 0.0), 0.9)

    return (_random.random() < p, p)


def _bump_leak(category: str) -> str:
    try:
        idx = _LEAK_ORDER.index(category)
    except ValueError:
        return category
    return _LEAK_ORDER[min(idx + 1, len(_LEAK_ORDER) - 1)]


# Action durations (real wall-clock seconds). Compressed for alpha
# playability; DESIGN.md §4.3 specifies longer realistic values.
# Override via SCP_TIME_SCALE env var (e.g. 10.0 = design-target durations).
_TS = float(os.environ.get("SCP_TIME_SCALE", "1.0"))


def _dur(seconds: float) -> timedelta:
    return timedelta(seconds=seconds * _TS)


SCAN_DURATION = _dur(30)
ACQUIRE_DURATION = _dur(5)
ANALYZE_DURATION = {
    "Safe": _dur(30),
    "Euclid": _dur(60),
    "Keter": _dur(180),
}
ARCHIVE_DURATION = _dur(30)
WIPE_DURATION = _dur(60)

ARCHIVE_REWARD = {"Safe": 50_000, "Euclid": 200_000, "Keter": 1_000_000}
STARTING_FUNDING = 1_000_000

# XP awarded on action completion
ANALYZE_SUCCESS_XP = {"Safe": 3, "Euclid": 6, "Keter": 12}
ANALYZE_FAILURE_XP_INFOSEC = 2
ANALYZE_FAILURE_XP_FORENSICS = 3
ARCHIVE_XP = 2
WIPE_XP_FORENSICS = 4
SCAN_XP = 1


def bootstrap_if_empty(journal: Journal) -> None:
    """Seed one site, one host, one VM, one tape drive, starting funds,
    and a small roster (player + 2 NPCs) on first daemon launch."""
    if journal.count_sites() > 0:
        return

    site_id = journal.create_site("Site-17-ALPHA", "onprem_dc")
    # Starter site: 20 kW power budget + 20 kW cooling — enough for one 2U server
    # plus headroom. Exceeding either shows in sitrep (Phase 2a: warning only).
    journal.set_site_capacity(site_id, power_kw=20, cooling_kw=20)
    # Default network tier: business fiber (1 Gbps, low latency).
    journal.set_site_network(site_id, "business_fiber")
    # Default encryption: software VPN — enough for Safe-class over commercial
    # fiber. Upgrade to hardware/Type-1 before handling Euclid/Keter.
    journal.set_site_encryption(site_id, "software")
    host_id = journal.create_host(
        site_id=site_id,
        name="host-01",
        host_class="server",
        specs={
            "cpu": "16c",
            "ram_gb": 64,
            "storage_gb": 2_000,           # 2 TB onboard storage
            "power_w": 400,
            "heat_btu_hr": round(400 * 3.41),
        },
        status="clean",
    )
    journal.create_vm(
        host_id=host_id,
        name="vm-01",
        spec=seed_vm_spec().to_dict(),
        status="idle",
    )
    journal.create_tape_drive(site_id=site_id, name="tape-01")
    # Starter cold-archive: 500 TB LTO library so first archives succeed
    journal.create_tape_library(site_id=site_id, sku="tape-lib-small",
                                capacity_gb=500_000)
    # Initial site ships with enough battery + fuel to cover itself for the
    # starting workload. Expansions will require purchased additions.
    journal.add_site_battery(site_id, 10)        # ~25h @ 0.4 kW
    journal.add_site_fuel(site_id, 72)           # 3-day fuel reserve
    journal.set_funding(STARTING_FUNDING)

    if journal.count_staff() == 0:
        journal.create_staff(
            name="Site Director (you)",
            role="player",
            is_player=True,
            skills={"infosec": 30, "memetics": 10, "forensics": 20},
            clearance=3,
            salary=0,
            assigned_site_id=site_id,
        )
        journal.create_staff(
            name="Dr. Vey",
            role="analyst",
            is_player=False,
            skills={"infosec": 25, "memetics": 15, "forensics": 10},
            clearance=2,
            salary=120_000,
            assigned_site_id=site_id,
        )
        journal.create_staff(
            name="Tech Osei",
            role="forensics_tech",
            is_player=False,
            skills={"infosec": 15, "memetics": 5, "forensics": 30},
            clearance=1,
            salary=90_000,
            assigned_site_id=site_id,
        )

    journal.append(
        "bootstrap",
        "INFO",
        {
            "site_id": site_id,
            "host_id": host_id,
            "starting_funding": STARTING_FUNDING,
        },
    )


# --- VM provisioning --------------------------------------------------
#
# VMs on the same host share the host's RAM evenly (host_ram / vm_count).
# Adding a VM shrinks every sibling's allocation, so crowding a 64 GB
# host with 4 VMs gives each only 16 GB. An analysis can only run if the
# item's size_gb fits in its VM's allocated_ram_gb.
#
# Max VMs per host is gated by both a per-class cap and a per-VM RAM floor
# (min 8 GB). A 64 GB server: 8 VMs. A 256 GB server: 32. A 2 TB
# mainframe: 64 (LPAR-style ceiling).

_MIN_RAM_PER_VM_GB = 8
_MAX_VMS_BY_CLASS = {
    "server":    32,
    "aipod":     16,
    "mainframe": 64,
}


def max_vms_for_host(host: dict) -> int:
    host_ram = int(host.get("specs", {}).get("ram_gb", 0) or 0)
    by_ram = max(1, host_ram // _MIN_RAM_PER_VM_GB)
    by_class = _MAX_VMS_BY_CLASS.get(host.get("class", "server"), 16)
    return min(by_ram, by_class)


def vm_allocated_ram_gb(journal: Journal, vm_id: int) -> int:
    vm = journal.get_vm(vm_id)
    if vm is None:
        return 0
    host = journal.get_host(vm["host_id"])
    if host is None:
        return 0
    host_ram = int(host.get("specs", {}).get("ram_gb", 0) or 0)
    n = max(1, journal.count_vms_on_host(vm["host_id"]))
    return host_ram // n


def _host_base_vm_spec(host: dict) -> dict:
    """Return the containment spec every new VM on this host should
    inherit. Preference order:

    1. `auto_vm_spec` stored on the host's specs (procurement stashes
       it there when a SKU with `auto_vm_spec` is installed — this is
       the canonical path).
    2. Backfill for older saves: resolve the SKU from the host name
       pattern `host-<sku_id>-<purchase_id>` and read its catalog
       `auto_vm_spec` capability.
    3. Otherwise the generic seed spec.

    This is why a mainframe LPAR shows up with base containment ~30
    while a generic 2U server shows up with a near-zero seed — the
    hardware itself brings memory encryption / LPAR isolation /
    firmware-level mnestics along for the ride.
    """
    specs = host.get("specs", {}) or {}
    stored = specs.get("auto_vm_spec")
    if isinstance(stored, dict) and stored:
        return dict(stored)

    # Backfill for hosts whose specs were written before auto_vm_spec
    # was stashed on the row. Name format is "host-<sku>-<purchase_id>".
    name = host.get("name", "") or ""
    if name.startswith("host-"):
        stripped = name[5:]
        last_dash = stripped.rfind("-")
        if last_dash > 0 and stripped[last_dash + 1:].isdigit():
            sku_id = stripped[:last_dash]
            from .hardware import catalog as _hw
            sku = _hw.get(sku_id)
            if sku is not None:
                avs = sku.capabilities.get("auto_vm_spec")
                if isinstance(avs, dict) and avs:
                    return dict(avs)
    return seed_vm_spec().to_dict()


def provision_vm(
    journal: Journal, host_id: int, name: str | None = None
) -> dict:
    """Create an additional VM on a host. Splits the host RAM across all
    VMs; refuses if no headroom or any sibling VM is busy. The new VM
    inherits the host's base containment spec (mainframes seed LPARs
    with ~30, servers seed with the generic low-base spec)."""
    host = journal.get_host(host_id)
    if host is None:
        raise ValueError(f"no host {host_id}")
    if host["status"] != "clean":
        raise ValueError(
            f"host {host_id} is '{host['status']}'; only clean hosts can host new VMs"
        )

    existing_count = journal.count_vms_on_host(host_id)
    cap = max_vms_for_host(host)
    if existing_count >= cap:
        raise ValueError(
            f"host {host_id} at VM capacity ({existing_count}/{cap}); "
            f"add RAM or use a bigger host"
        )

    # Adding a VM shrinks every sibling's allocation — refuse while any
    # sibling is mid-analysis, otherwise we'd yank RAM out from under it.
    siblings = [v for v in journal.list_vms() if v["host_id"] == host_id]
    busy = [v for v in siblings if v["status"] == "busy"]
    if busy:
        raise ValueError(
            f"cannot add VM while siblings are busy: "
            f"{', '.join(str(v['id']) for v in busy)}. Wait for analyses to complete."
        )

    new_name = name or f"vm-{host_id}-{existing_count + 1:02d}"
    base_spec = _host_base_vm_spec(host)
    vm_id = journal.create_vm(
        host_id=host_id,
        name=new_name,
        spec=base_spec,
        status="idle",
    )
    # Report the new per-VM RAM allocation for all siblings on the host.
    host_ram = int(host.get("specs", {}).get("ram_gb", 0) or 0)
    new_count = existing_count + 1
    allocated = host_ram // new_count
    base_containment = sum(int(v) for v in base_spec.values())
    journal.append(
        "vm_provisioned",
        "INFO",
        {
            "vm_id": vm_id,
            "host_id": host_id,
            "name": new_name,
            "host_ram_gb": host_ram,
            "vm_count": new_count,
            "allocated_ram_gb": allocated,
            "base_containment": base_containment,
            "base_spec": base_spec,
        },
    )
    return {
        "vm_id": vm_id,
        "host_id": host_id,
        "name": new_name,
        "host_ram_gb": host_ram,
        "vm_count": new_count,
        "allocated_ram_gb": allocated,
        "max_vms": cap,
        "base_containment": base_containment,
        "base_spec": base_spec,
    }


def deprovision_vm(journal: Journal, vm_id: int) -> dict:
    """Tear down a VM. Refuses if the VM is mid-analysis. Items or
    mistake rows referencing this VM are left in place (current_vm_id
    is cleared on the item side). The freed RAM share is redistributed
    across remaining VMs on the host."""
    vm = journal.get_vm(vm_id)
    if vm is None:
        raise ValueError(f"no vm {vm_id}")
    if vm["status"] == "busy":
        raise ValueError(
            f"vm {vm_id} is busy; wait for the in-flight analysis to finish "
            f"or cancel before deprovisioning"
        )
    host_id = vm["host_id"]

    # Clear any item's current_vm_id pointer at this VM so foreign rows
    # don't dangle. (Items in 'quarantined' with no VM are still valid;
    # they just aren't tethered to a specific VM anymore.)
    for it in journal.list_items():
        if it.get("current_vm_id") == vm_id:
            journal.set_item_state(
                it["id"], it["state"], current_vm_id=None
            )

    journal._conn.execute("DELETE FROM vms WHERE id = ?", (int(vm_id),))

    remaining = journal.count_vms_on_host(host_id)
    host = journal.get_host(host_id)
    host_ram = int((host or {}).get("specs", {}).get("ram_gb", 0) or 0)
    new_alloc = host_ram // max(1, remaining) if remaining else 0
    result = {
        "vm_id": vm_id,
        "host_id": host_id,
        "name": vm["name"],
        "remaining_vms_on_host": remaining,
        "allocated_ram_gb_each": new_alloc,
        "host_ram_gb": host_ram,
    }
    journal.append("vm_deprovisioned", "INFO", result)
    return result


def _resolve_operator(journal: Journal, operator_id: int | None) -> dict:
    if operator_id is None:
        op = journal.get_player()
        if not op:
            raise RuntimeError("no player staff record")
    else:
        op = journal.get_staff(operator_id)
        if not op:
            raise ValueError(f"no staff with id {operator_id}")
    if op["status"] != "active":
        raise ValueError(
            f"{op['name']} is {op['status']}, not active; can't be assigned"
        )
    return op


# --- action initiators -------------------------------------------------


def start_scan(journal: Journal, schedule_fn: Any, operator_id: int | None = None) -> dict:
    op = _resolve_operator(journal, operator_id)
    eta = now_utc() + SCAN_DURATION
    sid = schedule_fn(eta, "scan_complete", {"operator_id": op["id"]})
    journal.append(
        "scan_started", "INFO", {"scheduled_id": sid, "operator_id": op["id"]}
    )
    return {"scheduled_id": sid, "eta": eta.isoformat(), "operator": op["name"]}


def acquire_candidate(
    journal: Journal,
    item_id: int,
    operator_id: int | None = None,
    target_site_id: int | None = None,
) -> dict:
    op = _resolve_operator(journal, operator_id)
    item = journal.get_item(item_id)
    if not item:
        raise ValueError(f"no item {item_id}")
    if item["state"] != "candidate":
        raise ValueError(f"item {item_id} is {item['state']}, not candidate")

    # Decide where to put the acquired payload. Default: first site.
    sites = journal.list_sites()
    if not sites:
        raise ValueError("no sites available for quarantine")
    if target_site_id is None:
        target_site_id = sites[0]["id"]
    elif not any(s["id"] == target_site_id for s in sites):
        raise ValueError(f"no site with id {target_site_id}")

    # Storage capacity check
    size_gb = float(item.get("size_gb", 0) or 0)
    util = procurement.site_utilization(journal, target_site_id)
    free_gb = util["storage_cap_gb"] - util["storage_used_gb"]
    if size_gb > free_gb:
        raise ValueError(
            f"insufficient quarantine storage at site {target_site_id}: "
            f"need {size_gb:.1f} GB, free {free_gb:.1f} GB "
            f"(cap {util['storage_cap_gb']:.1f} GB)"
        )

    # Auto-encrypt at rest if site has any encryption installed
    site_enc = journal.get_site_encryption(target_site_id)
    encrypted = site_enc != "none"

    journal.set_item_state(item_id, "quarantined", current_vm_id=None)
    journal.set_item_site(item_id, target_site_id)
    journal.set_item_encryption(item_id, encrypted)
    journal.grant_xp(op["id"], "infosec", 1)
    journal.append(
        "item_acquired",
        "INFO",
        {
            "item_id": item_id,
            "operator_id": op["id"],
            "site_id": target_site_id,
            "size_gb": size_gb,
            "encrypted_at_rest": encrypted,
        },
    )
    if not encrypted:
        journal.append(
            "unencrypted_at_rest",
            "NOTICE",
            {
                "item_id": item_id,
                "site_id": target_site_id,
                "reason": "site encryption level is 'none'",
            },
        )
    return {
        "item_id": item_id,
        "state": "quarantined",
        "operator": op["name"],
        "site_id": target_site_id,
        "size_gb": size_gb,
        "encrypted_at_rest": encrypted,
    }


def start_analyze(
    journal: Journal,
    schedule_fn: Any,
    item_id: int,
    vm_id: int,
    operator_id: int | None = None,
    override: bool = False,
) -> dict:
    op = _resolve_operator(journal, operator_id)
    item = journal.get_item(item_id)
    if not item:
        raise ValueError(f"no item {item_id}")
    if item["state"] != "quarantined":
        raise ValueError(
            f"item {item_id} is {item['state']}, must be quarantined to analyze"
        )
    vm = journal.get_vm(vm_id)
    if not vm:
        raise ValueError(f"no vm {vm_id}")
    if vm["host_status"] == "wiping":
        raise ValueError(f"vm {vm_id}'s host is being wiped")
    if vm["status"] == "busy":
        raise ValueError(f"vm {vm_id} is busy")
    if vm["status"] == "offline":
        raise ValueError(f"vm {vm_id} is offline")

    # RAM gate: the item must fit in the VM's allocated memory. VMs on the
    # same host share the host's RAM evenly (host_ram / vm_count), so
    # crowding a host with more VMs shrinks the per-VM memory budget. A
    # 500 GB Keter item can't be analyzed on a 64 GB host, and you can't
    # squeeze it onto a 256 GB host if you've split it into 8 VMs either.
    allocated_ram_gb = vm_allocated_ram_gb(journal, vm_id)
    item_size_gb = float(item.get("size_gb", 0) or 0)
    if item_size_gb > allocated_ram_gb:
        raise ValueError(
            f"item {item_id} ({item_size_gb:.0f} GB) does not fit in VM {vm_id} "
            f"({allocated_ram_gb} GB allocated). Add host RAM, consolidate VMs "
            f"on this host, or move the item to a bigger host."
        )

    # Run mistake detection + guardrail (includes site overload / link checks)
    host = journal.get_host(vm["host_id"])
    site_util = None
    site_tier_dict = None
    site_encryption = "none"
    if host is not None:
        site_id = host["site_id"]
        site_util = procurement.site_utilization(journal, site_id)
        tier = network.get(journal.get_site_network(site_id) or "business_fiber")
        if tier is not None:
            site_tier_dict = tier.to_dict()
        site_encryption = journal.get_site_encryption(site_id)
    detection = mistakes.detect_analyze_mistakes(
        op, item, vm,
        site_util=site_util,
        site_network_tier=site_tier_dict,
        site_encryption_level=site_encryption,
    )
    operator_skill = int(op["skills"].get("infosec", 0))
    decision = guardrail.decide(detection, operator_skill, override)

    if not decision.allowed:
        return {
            "blocked": True,
            "rail_level": decision.rail_level,
            "require_override": decision.require_override,
            "refuse_reason": decision.refuse_reason,
            "warnings": decision.warnings,
            "mistake_kinds": decision.mistake_kinds,
        }

    # Persist mistakes (if any) before the action proceeds
    mistake_ids: list[int] = []
    for m in detection.mistakes:
        mid = journal.record_mistake(
            kind=m.kind,
            action="analyze",
            operator_id=op["id"],
            item_id=item_id,
            host_id=vm["host_id"],
            vm_id=vm_id,
            overridden=(decision.rail_level == "soft"),
            details={
                "title": m.title,
                "detail": m.detail,
                "suggestion": m.suggestion,
                "severity_weight": m.severity_weight,
                "rail_level": decision.rail_level,
            },
        )
        mistake_ids.append(mid)

    base_duration = ANALYZE_DURATION.get(item["class"], ANALYZE_DURATION["Euclid"])
    # AI pod analysis speedup: hosts tagged with analysis_speedup in specs
    # divide the analyze duration accordingly (1.0 = no change).
    speedup = 1.0
    if host is not None:
        try:
            speedup = float(host.get("specs", {}).get("analysis_speedup", 1.0))
        except (TypeError, ValueError):
            speedup = 1.0
    # Operator-skill speed bonus: at skill 0 no bonus; at skill 100 up to 40% faster.
    skill_factor = 1.0 - (operator_skill / 250)   # 0→1.0, 100→0.6
    # Compute satellites: each on-orbit compute sat cuts 10%, capped at 50%.
    compute_sats = journal.count_satellites(payload="compute")
    compute_factor = max(1.0 - min(compute_sats * 0.10, 0.50), 0.5)
    # Latency penalty: high-p99 connections slow Euclid+ analyses
    latency_factor = 1.0
    if host is not None and item["class"] != "Safe":
        tier_data = network.get(journal.get_site_network(host["site_id"]) or "business_fiber")
        if tier_data is not None:
            if tier_data.latency_p99_ms >= 100:
                latency_factor = 1.25
            elif tier_data.latency_p99_ms >= 50:
                latency_factor = 1.10
    duration = (
        base_duration / max(speedup, 0.1)
        * skill_factor * latency_factor * compute_factor
    )
    eta = now_utc() + duration
    sid = schedule_fn(
        eta,
        "analyze_complete",
        {
            "item_id": item_id,
            "vm_id": vm_id,
            "operator_id": op["id"],
            "mistake_ids": mistake_ids,
        },
    )
    journal.set_item_state(item_id, "analyzing", current_vm_id=vm_id)
    journal.set_vm_status(vm_id, "busy")
    journal.append(
        "analysis_started",
        "INFO",
        {
            "scheduled_id": sid,
            "item_id": item_id,
            "vm_id": vm_id,
            "operator_id": op["id"],
            "operator_name": op["name"],
            "rail_level": decision.rail_level,
            "mistake_ids": mistake_ids,
            "eta": eta.isoformat(),
            "item_class": item["class"],
            "hazard": item["hazard_strength"],
            "containment": VmSpec.from_dict(vm["spec"]).containment,
        },
    )
    return {
        "scheduled_id": sid,
        "eta": eta.isoformat(),
        "operator": op["name"],
        "rail_level": decision.rail_level,
        "warnings": decision.warnings,
        "mistake_kinds": decision.mistake_kinds,
    }


def start_archive(
    journal: Journal,
    schedule_fn: Any,
    item_id: int,
    operator_id: int | None = None,
    target_site_id: int | None = None,
) -> dict:
    op = _resolve_operator(journal, operator_id)
    item = journal.get_item(item_id)
    if not item:
        raise ValueError(f"no item {item_id}")
    if item["state"] != "analyzed":
        raise ValueError(
            f"item {item_id} is {item['state']}, must be analyzed to archive"
        )

    source_site_id = item.get("current_site_id")
    if target_site_id is None:
        target_site_id = source_site_id   # default: archive in place
    else:
        if not any(s["id"] == target_site_id for s in journal.list_sites()):
            raise ValueError(f"no site with id {target_site_id}")

    size_gb = float(item.get("size_gb", 0) or 0)
    duration = ARCHIVE_DURATION
    transmission_s = 0.0
    if (
        source_site_id is not None
        and target_site_id is not None
        and int(source_site_id) != int(target_site_id)
    ):
        # Transmission time scales with the slower of source/dest link bandwidth.
        src_tier = network.get(
            journal.get_site_network(source_site_id) or "business_fiber"
        )
        dst_tier = network.get(
            journal.get_site_network(target_site_id) or "business_fiber"
        )
        if src_tier is not None and dst_tier is not None:
            min_mbps = min(src_tier.bandwidth_mbps, dst_tier.bandwidth_mbps)
            # Mbps × 0.000125 → GB/s; 80% protocol efficiency
            gb_per_s = max(min_mbps * 0.000125 * 0.8, 1e-6)
            transmission_s = size_gb / gb_per_s
            duration = ARCHIVE_DURATION + timedelta(
                seconds=transmission_s * _TS
            )

    eta = now_utc() + duration
    sid = schedule_fn(
        eta,
        "archive_complete",
        {
            "item_id": item_id,
            "operator_id": op["id"],
            "target_site_id": target_site_id,
        },
    )
    journal.set_item_state(item_id, "archiving", current_vm_id=None)
    if target_site_id is not None and target_site_id != source_site_id:
        journal.set_item_transit(item_id, int(target_site_id))
    journal.append(
        "archive_started",
        "INFO",
        {
            "scheduled_id": sid,
            "item_id": item_id,
            "operator_id": op["id"],
            "source_site_id": source_site_id,
            "target_site_id": target_site_id,
            "size_gb": size_gb,
            "transmission_s_unscaled": round(transmission_s, 2),
            "eta": eta.isoformat(),
        },
    )
    return {
        "scheduled_id": sid,
        "eta": eta.isoformat(),
        "operator": op["name"],
        "source_site_id": source_site_id,
        "target_site_id": target_site_id,
        "size_gb": size_gb,
    }


def start_wipe(
    journal: Journal,
    schedule_fn: Any,
    host_id: int,
    operator_id: int | None = None,
) -> dict:
    op = _resolve_operator(journal, operator_id)
    host = journal.get_host(host_id)
    if not host:
        raise ValueError(f"no host {host_id}")
    if host["status"] not in ("infected", "glitchy", "suspect"):
        raise ValueError(
            f"host {host_id} is {host['status']}; wipe is for compromised hosts"
        )
    eta = now_utc() + WIPE_DURATION
    sid = schedule_fn(
        eta, "wipe_complete", {"host_id": host_id, "operator_id": op["id"]}
    )
    journal.set_host_status(host_id, "wiping")
    journal.set_vms_on_host_status(host_id, "offline")
    journal.append(
        "wipe_started",
        "INFO",
        {
            "scheduled_id": sid,
            "host_id": host_id,
            "operator_id": op["id"],
            "eta": eta.isoformat(),
        },
    )
    return {"scheduled_id": sid, "eta": eta.isoformat(), "operator": op["name"]}


# --- scheduled-fire completions ----------------------------------------


def on_scan_complete(
    journal: Journal, rng: random.Random, operator_id: int | None = None
) -> dict:
    # SIGINT satellites fatten scan yield: each adds +1 to the upper bound.
    sigint_count = journal.count_satellites(payload="sigint")
    upper = 3 + sigint_count
    n = rng.randint(1, max(1, upper))
    ids: list[int] = []
    for _ in range(n):
        p = generate_item(rng)
        iid = journal.create_item(
            designation=p.designation,
            item_class=p.item_class,
            hazard_strength=p.hazard_strength,
            profile=p.to_dict(),
            state="candidate",
        )
        ids.append(iid)
    if operator_id is not None:
        journal.grant_xp(operator_id, "infosec", SCAN_XP)
    journal.append(
        "scan_complete",
        "INFO",
        {
            "item_ids": ids,
            "count": n,
            "operator_id": operator_id,
            "sigint_boost": sigint_count,
        },
    )
    return {"item_ids": ids, "count": n}


def on_analyze_complete(
    journal: Journal,
    item_id: int,
    vm_id: int,
    operator_id: int | None = None,
    mistake_ids: list[int] | None = None,
) -> dict:
    item = journal.get_item(item_id)
    vm = journal.get_vm(vm_id)
    if not item or not vm:
        return {"error": "item or vm not found"}
    host = journal.get_host(vm["host_id"])
    assert host is not None
    operator = journal.get_staff(operator_id) if operator_id is not None else None
    mistake_ids = mistake_ids or []

    spec = VmSpec.from_dict(vm["spec"])
    containment = spec.containment
    cat = leak_category(item["hazard_strength"], containment)
    delta = item["hazard_strength"] - containment

    # Brownout check: overloaded power/cooling at analysis completion can
    # promote the leak tier by one step.
    site_util_now = procurement.site_utilization(journal, host["site_id"])
    brownout_hit, brownout_p = _maybe_brownout(site_util_now)
    original_cat = cat
    if brownout_hit:
        cat = _bump_leak(cat)

    outcome: dict = {
        "item_id": item_id,
        "vm_id": vm_id,
        "host_id": host["id"],
        "category": cat,
        "hazard": item["hazard_strength"],
        "containment": containment,
        "delta": delta,
        "operator_id": operator_id,
        "brownout": brownout_hit,
        "brownout_probability": round(brownout_p, 3),
        "original_category": original_cat,
    }

    if brownout_hit:
        journal.append(
            "brownout_promoted_leak",
            "ALERT",
            {
                "item_id": item_id,
                "vm_id": vm_id,
                "host_id": host["id"],
                "from": original_cat,
                "to": cat,
                "probability": round(brownout_p, 3),
            },
        )

    journal.set_item_state(item_id, "analyzed", current_vm_id=None)
    # Remember which site this item was handled at, for future archive/transit.
    if host is not None:
        journal.set_item_site(item_id, int(host["site_id"]))

    # Effects on VM/host state
    if cat == "stable":
        journal.set_vm_status(vm_id, "idle")
    elif cat == "slow_leak":
        journal.set_vm_status(vm_id, "tainted")
    else:  # active_leak or catastrophic
        journal.set_vm_status(vm_id, "tainted")
        journal.set_host_status(host["id"], "infected")

    # XP
    if operator is not None:
        if cat == "stable":
            journal.grant_xp(
                operator["id"], "infosec", ANALYZE_SUCCESS_XP.get(item["class"], 3)
            )
        else:
            journal.grant_xp(operator["id"], "infosec", ANALYZE_FAILURE_XP_INFOSEC)
            journal.grant_xp(
                operator["id"], "forensics", ANALYZE_FAILURE_XP_FORENSICS
            )

    # Journal event
    if cat == "stable":
        journal.append("analysis_stable", "INFO", outcome)
    elif cat == "slow_leak":
        journal.append("analysis_slow_leak", "NOTICE", outcome)
    else:
        sev = "ALERT" if cat == "active_leak" else "BREACH"
        journal.append(f"analysis_{cat}", sev, outcome)

    # Incident report on any non-stable outcome
    if cat != "stable":
        # Refresh host (may have just been set to infected)
        host = journal.get_host(vm["host_id"]) or host
        vm = journal.get_vm(vm_id) or vm
        incident_id = incidents.persist(
            journal,
            item=item,
            host=host,
            vm=vm,
            operator=operator,
            category=cat,
            hazard=item["hazard_strength"],
            containment=containment,
            mistake_ids=mistake_ids,
        )
        outcome["incident_id"] = incident_id
        outcome["severity"] = incidents.CATEGORY_SEVERITY[cat]
        inc = journal.get_incident(incident_id)
        if inc:
            outcome["report"] = inc["report"]

    return outcome


def on_archive_complete(
    journal: Journal,
    item_id: int,
    operator_id: int | None = None,
    target_site_id: int | None = None,
) -> dict:
    item = journal.get_item(item_id)
    if not item:
        return {"error": "item not found"}

    # Pick archive destination: explicit target > item's transit dest >
    # item's current site > first site with free tape space.
    size_gb = float(item.get("size_gb", 0) or 0)
    if target_site_id is not None:
        destination_site = int(target_site_id)
    elif item.get("transit_to_site_id") is not None:
        destination_site = int(item["transit_to_site_id"])
    else:
        destination_site = item.get("current_site_id")
    if destination_site is not None:
        util = procurement.site_utilization(journal, destination_site)
        free = util["tape_cap_gb"] - util["tape_used_gb"]
        if size_gb > free:
            # Try any other site with capacity
            for s in journal.list_sites():
                if s["id"] == destination_site:
                    continue
                u2 = procurement.site_utilization(journal, s["id"])
                if (u2["tape_cap_gb"] - u2["tape_used_gb"]) >= size_gb:
                    destination_site = s["id"]
                    break
            else:
                # No site with capacity — promote to WARNING, leave item
                # in analyzed state, item is not archived.
                journal.append(
                    "archive_overflow",
                    "ALERT",
                    {
                        "item_id": item_id,
                        "size_gb": size_gb,
                        "reason": "no site has sufficient tape capacity",
                    },
                )
                journal.set_item_state(item_id, "analyzed", current_vm_id=None)
                return {
                    "error": "no tape capacity available",
                    "item_id": item_id,
                    "size_gb": size_gb,
                }

    reward = ARCHIVE_REWARD.get(item["class"], 0)
    # Storage satellites: Foundation pays a premium (+25% per orbital storage sat,
    # capped at +100%) for items archived against an on-orbit backup.
    storage_sats = journal.count_satellites(payload="storage")
    storage_bonus = min(storage_sats * 0.25, 1.0)
    if storage_bonus:
        reward = int(reward * (1.0 + storage_bonus))
    new_balance = journal.adjust_funding(reward)
    journal.set_item_state(item_id, "archived", current_vm_id=None)
    # Clear any transit marker left over from the archive request
    if item.get("transit_to_site_id") is not None:
        journal.set_item_transit(item_id, None)
    if destination_site is not None:
        journal.set_item_site(item_id, int(destination_site))
    else:
        # Legacy fallback: no site tracked at all — park at first tape drive
        drives = journal.list_tape_drives()
        if drives:
            journal.set_item_site(item_id, int(drives[0]["site_id"]))
    if operator_id is not None:
        journal.grant_xp(operator_id, "infosec", ARCHIVE_XP)
    result = {
        "item_id": item_id,
        "designation": item["designation"],
        "class": item["class"],
        "reward": reward,
        "balance": new_balance,
        "operator_id": operator_id,
    }
    journal.append("item_archived", "INFO", result)
    return result


def on_wipe_complete(
    journal: Journal, host_id: int, operator_id: int | None = None
) -> dict:
    journal.set_host_status(host_id, "clean")
    journal.set_vms_on_host_status(host_id, "idle")
    if operator_id is not None:
        journal.grant_xp(operator_id, "forensics", WIPE_XP_FORENSICS)
    journal.append(
        "wipe_complete", "INFO", {"host_id": host_id, "operator_id": operator_id}
    )
    return {"host_id": host_id, "operator_id": operator_id}


# --- read helpers for TUI ---------------------------------------------


def sitrep(journal: Journal) -> dict:
    sites = journal.list_sites()
    utilization = [procurement.site_utilization(journal, s["id"]) for s in sites]
    site_networks = {}
    site_encryption_map = {}
    for s in sites:
        tier_id = journal.get_site_network(s["id"]) or "business_fiber"
        tier = network.get(tier_id)
        site_networks[s["id"]] = tier.to_dict() if tier else {"tier": tier_id}
        site_encryption_map[s["id"]] = journal.get_site_encryption(s["id"])
    return {
        "funding": journal.get_funding(),
        "player": journal.get_player(),
        "staff": journal.list_staff(),
        "sites": sites,
        "utilization": utilization,
        "site_networks": site_networks,
        "site_encryption": site_encryption_map,
        "hosts": journal.list_hosts(),
        "vms": journal.list_vms(),
        "tape_drives": journal.list_tape_drives(),
        "candidates": journal.list_items("candidate"),
        "quarantined": journal.list_items("quarantined"),
        "analyzing": journal.list_items("analyzing"),
        "analyzed": journal.list_items("analyzed"),
        "archiving": journal.list_items("archiving"),
        "archived_count": len(journal.list_items("archived")),
        "open_incidents": len(journal.list_incidents(200)),
        "pending_purchases": len(journal.list_purchases("ordered")),
        "active_contracts": len(journal.list_contracts(status="active")),
    }
