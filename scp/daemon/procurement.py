from __future__ import annotations

from datetime import timedelta
from typing import Any

from .clock import iso, now_utc
from .containment import seed_vm_spec
from .hardware.catalog import get as get_sku
from .journal import Journal


HOST_CATEGORIES = {"server", "aipod", "mainframe"}
# compute_module is a compound asset that installs multiple hosts + cooling
# in a single purchase. Targets a site like a regular host.
COMPUTE_MODULE_CATEGORIES = {"compute_module"}
SITE_CATEGORIES = {"site_encryption", "airfield", "port", "ground_station"}
ORBITAL_CATEGORIES = {"satellite"}
SUBMARINE_CATEGORIES = {"submarine"}
POWER_PLANT_CATEGORIES = {"power_plant"}
RESILIENCE_CATEGORIES = {"battery_bank", "fuel_storage"}
STORAGE_CATEGORIES = {"storage_array", "tape_library"}
HOST_MODULE_CATEGORIES = {"host_module"}
# Per-host containment upgrades that also cascade to every VM on the host.
HOST_CONTAINMENT_MODULE_CATEGORIES = {"host_containment_module"}
PUMP_CATEGORIES = {"pump_system"}
COOLING_CATEGORIES = {"cooling_unit"}
AIRFIELD_RANK = ["none", "dirt_strip", "small_airport", "private_airfield"]
PORT_RANK = ["none", "small_port", "deepwater_port"]


def _airfield_rank(tier: str) -> int:
    try:
        return AIRFIELD_RANK.index(tier)
    except ValueError:
        return 0


def _port_rank(tier: str) -> int:
    try:
        return PORT_RANK.index(tier)
    except ValueError:
        return 0


# Stealth / ISR SKU membership (by SKU id prefix) for chained gating.
_STEALTH_SKUS = {"raptor-22", "lightning-35", "phantom-47", "blackbird-71"}
_ISR_SKUS = {
    "oceanhawk-mpa", "skywatch-awacs", "rivergaze-rc135",
    "groundtrack-jstars", "spyglass-u2",
}


def _airframe_is_stealth(sku_id: str) -> bool:
    return sku_id in _STEALTH_SKUS


def _airframe_is_isr(sku_id: str) -> bool:
    return sku_id in _ISR_SKUS


def buy(
    journal: Journal,
    schedule_fn: Any,
    sku_id: str,
    target_site_id: int | None = None,
    target_vm_id: int | None = None,
) -> dict:
    sku = get_sku(sku_id)
    if sku is None:
        raise ValueError(f"unknown sku: {sku_id}")

    sites = journal.list_sites()
    if not sites:
        raise ValueError("no sites exist")

    is_host = sku.category in HOST_CATEGORIES
    is_compute_module = sku.category in COMPUTE_MODULE_CATEGORIES
    is_site_module = sku.category in SITE_CATEGORIES
    is_aircraft = sku.category == "aircraft"
    is_ship = sku.category == "ship"
    is_submarine = sku.category in SUBMARINE_CATEGORIES
    is_orbital = sku.category in ORBITAL_CATEGORIES
    is_power_plant = sku.category in POWER_PLANT_CATEGORIES
    is_resilience = sku.category in RESILIENCE_CATEGORIES
    is_storage = sku.category in STORAGE_CATEGORIES
    is_host_module = sku.category in HOST_MODULE_CATEGORIES
    is_host_containment_module = (
        sku.category in HOST_CONTAINMENT_MODULE_CATEGORIES
    )
    is_pump = sku.category in PUMP_CATEGORIES
    is_cooling = sku.category in COOLING_CATEGORIES
    is_module = sku.category == "vm_module"

    if is_orbital:
        # Satellites don't tie to a site; but OTV/specials may be gated.
        gate_geo = int(sku.capabilities.get("gate_min_geo_satellites", 0))
        if gate_geo > 0:
            # Count on-orbit GEO comms satellites (proxy for Foundation presence).
            geo_count = sum(
                1 for s in journal.list_satellites()
                if s.get("orbit") == "GEO" and s.get("status") == "on_orbit"
            )
            if geo_count < gate_geo:
                raise ValueError(
                    f"{sku.sku} requires {gate_geo} on-orbit GEO satellite(s); "
                    f"currently {geo_count}"
                )
        target_site_id = None
        target_vm_id = None
    elif is_submarine:
        if target_site_id is None:
            target_site_id = sites[0]["id"]
        if not any(s["id"] == target_site_id for s in sites):
            raise ValueError(f"no site with id {target_site_id}")
        needed = sku.capabilities.get("min_port", "small_port")
        current = journal.get_site_port(target_site_id)
        if _port_rank(current) < _port_rank(needed):
            raise ValueError(
                f"site {target_site_id} port '{current}' below "
                f"submarine minimum '{needed}'"
            )
        gate_subs = int(sku.capabilities.get("gate_min_submarines", 0))
        if gate_subs > 0 and journal.count_submarines() < gate_subs:
            raise ValueError(
                f"{sku.sku} requires {gate_subs} existing submarine(s); "
                f"currently {journal.count_submarines()}"
            )
        target_vm_id = None
    elif (is_host or is_compute_module or is_site_module or is_aircraft
          or is_ship or is_power_plant or is_resilience or is_storage
          or is_pump or is_cooling):
        if target_site_id is None:
            target_site_id = sites[0]["id"]
        if not any(s["id"] == target_site_id for s in sites):
            raise ValueError(f"no site with id {target_site_id}")
        if is_aircraft:
            needed = sku.capabilities.get("min_airfield", "dirt_strip")
            current = journal.get_site_airfield(target_site_id)
            if _airfield_rank(current) < _airfield_rank(needed):
                raise ValueError(
                    f"site {target_site_id} airfield '{current}' below "
                    f"aircraft minimum '{needed}'"
                )
            # Chained-stealth gate: e.g., F-47 needs 2 prior stealth aircraft.
            need_stealth = int(sku.capabilities.get("gate_min_owned_stealth", 0))
            if need_stealth > 0:
                owned_stealth = sum(
                    1 for ac in journal.list_aircraft()
                    if _airframe_is_stealth(ac.get("sku", ""))
                )
                if owned_stealth < need_stealth:
                    raise ValueError(
                        f"{sku.sku} requires {need_stealth} prior stealth "
                        f"airframe(s); currently {owned_stealth}"
                    )
            need_isr = int(sku.capabilities.get("gate_min_owned_isr", 0))
            if need_isr > 0:
                owned_isr = sum(
                    1 for ac in journal.list_aircraft()
                    if _airframe_is_isr(ac.get("sku", ""))
                )
                if owned_isr < need_isr:
                    raise ValueError(
                        f"{sku.sku} requires {need_isr} prior ISR airframe(s); "
                        f"currently {owned_isr}"
                    )
        if is_ship:
            needed = sku.capabilities.get("min_port", "small_port")
            current = journal.get_site_port(target_site_id)
            if _port_rank(current) < _port_rank(needed):
                raise ValueError(
                    f"site {target_site_id} port '{current}' below "
                    f"ship minimum '{needed}'"
                )
        target_vm_id = None
    elif is_module:
        if target_vm_id is None:
            vms = journal.list_vms()
            if not vms:
                raise ValueError("no VMs to upgrade")
            target_vm_id = vms[0]["id"]
        if journal.get_vm(int(target_vm_id)) is None:
            raise ValueError(f"no vm {target_vm_id}")
        target_site_id = None
    elif is_host_module or is_host_containment_module:
        # Host upgrades target an existing host by id; we stash the id in
        # target_vm_id so the existing purchase row can carry it.
        if target_vm_id is None:
            hosts = journal.list_hosts()
            if not hosts:
                raise ValueError("no hosts to upgrade")
            target_vm_id = hosts[0]["id"]
        if journal.get_host(int(target_vm_id)) is None:
            raise ValueError(f"no host {target_vm_id}")
        target_site_id = None
    else:
        raise ValueError(f"sku category '{sku.category}' not buyable in this phase")

    current = journal.get_funding()
    if current < sku.price_usd:
        raise ValueError(
            f"insufficient funding: ${current:,} < ${sku.price_usd:,}"
        )

    new_balance = journal.adjust_funding(-sku.price_usd)

    eta = now_utc() + timedelta(seconds=sku.lead_time_s)
    purchase_id = journal.create_purchase(
        sku=sku.sku,
        price_usd=sku.price_usd,
        target_site_id=target_site_id,
        target_vm_id=target_vm_id,
        eta_utc=eta,
    )
    sid = schedule_fn(eta, "install_complete", {"purchase_id": purchase_id})
    journal.append(
        "purchase_ordered",
        "INFO",
        {
            "purchase_id": purchase_id,
            "sku": sku.sku,
            "name": sku.name,
            "price_usd": sku.price_usd,
            "balance": new_balance,
            "eta": iso(eta),
            "target_site_id": target_site_id,
            "target_vm_id": target_vm_id,
        },
    )
    return {
        "purchase_id": purchase_id,
        "sku": sku.sku,
        "name": sku.name,
        "price_usd": sku.price_usd,
        "balance": new_balance,
        "eta": iso(eta),
        "scheduled_id": sid,
    }


def on_install_complete(journal: Journal, purchase_id: int) -> dict:
    p = journal.get_purchase(purchase_id)
    if not p:
        return {"error": f"no purchase {purchase_id}"}
    sku = get_sku(p["sku"])
    if sku is None:
        return {"error": f"unknown sku {p['sku']} on install"}

    result: dict = {
        "purchase_id": purchase_id,
        "sku": sku.sku,
        "name": sku.name,
        "category": sku.category,
    }

    if sku.category in HOST_CATEGORIES:
        # Stash auto_vm_spec INTO the host specs (not stripped) so future
        # provision_vm calls on this host inherit the same containment
        # baseline. Without this, the first VM (created here) gets the
        # boost but every additional VM would fall back to the seed spec.
        specs = {
            "power_w": sku.power_w,
            "heat_btu_hr": sku.heat_btu_hr,
            **{k: v for k, v in sku.capabilities.items()},
        }
        host_id = journal.create_host(
            site_id=p["target_site_id"],
            name=f"host-{sku.sku}-{purchase_id}",
            host_class=sku.capabilities.get("host_class", "server"),
            specs=specs,
            status="clean",
        )
        if sku.category == "mainframe":
            vm_spec = dict(sku.capabilities.get("auto_vm_spec") or {})
        else:
            avs = sku.capabilities.get("auto_vm_spec")
            vm_spec = dict(avs) if isinstance(avs, dict) and avs else seed_vm_spec().to_dict()
        vm_id = journal.create_vm(
            host_id=host_id,
            name=f"vm-{host_id}-01",
            spec=vm_spec,
            status="idle",
        )
        result["host_id"] = host_id
        result["vm_id"] = vm_id

    elif sku.category == "vm_module":
        target_vm = journal.get_vm(p["target_vm_id"])
        if not target_vm:
            result["error"] = f"target vm {p['target_vm_id']} no longer exists"
        else:
            comp = sku.capabilities.get("vm_component")
            value = int(sku.capabilities.get("value", 0))
            spec = dict(target_vm["spec"])
            before = int(spec.get(comp, 0))
            spec[comp] = max(before, value)
            journal.update_vm_spec(target_vm["id"], spec)
            result.update(
                {
                    "vm_id": target_vm["id"],
                    "component": comp,
                    "before": before,
                    "after": spec[comp],
                }
            )
    elif sku.category == "site_encryption":
        from .network import encryption_rank
        new_level = sku.capabilities.get("encryption_level", "none")
        site_id = p["target_site_id"]
        current = journal.get_site_encryption(site_id)
        if encryption_rank(new_level) > encryption_rank(current):
            journal.set_site_encryption(site_id, new_level)
            result.update(
                {"site_id": site_id, "before": current, "after": new_level}
            )
        else:
            result.update(
                {
                    "site_id": site_id,
                    "before": current,
                    "after": current,
                    "note": f"no upgrade (current {current} >= new {new_level})",
                }
            )
    elif sku.category == "airfield":
        new_tier = sku.capabilities.get("airfield_tier", "none")
        site_id = p["target_site_id"]
        current = journal.get_site_airfield(site_id)
        if _airfield_rank(new_tier) > _airfield_rank(current):
            journal.set_site_airfield(site_id, new_tier)
            result.update(
                {"site_id": site_id, "before": current, "after": new_tier}
            )
        else:
            result.update(
                {
                    "site_id": site_id,
                    "before": current,
                    "after": current,
                    "note": f"no upgrade (current {current} >= new {new_tier})",
                }
            )
    elif sku.category == "aircraft":
        site_id = p["target_site_id"]
        ac_class = sku.capabilities.get("aircraft_class", "ga_single")
        existing = journal.count_aircraft()
        tail = f"N{existing + 1:04d}X"
        ac_id = journal.create_aircraft(
            site_id=site_id,
            tail_number=tail,
            sku=sku.sku,
            aircraft_class=ac_class,
        )
        result.update(
            {"aircraft_id": ac_id, "tail_number": tail, "site_id": site_id}
        )
    elif sku.category == "port":
        new_tier = sku.capabilities.get("port_tier", "none")
        site_id = p["target_site_id"]
        current = journal.get_site_port(site_id)
        if _port_rank(new_tier) > _port_rank(current):
            journal.set_site_port(site_id, new_tier)
            result.update(
                {"site_id": site_id, "before": current, "after": new_tier}
            )
        else:
            result.update(
                {
                    "site_id": site_id,
                    "before": current,
                    "after": current,
                    "note": f"no upgrade (current {current} >= new {new_tier})",
                }
            )
    elif sku.category == "ship":
        site_id = p["target_site_id"]
        ship_class = sku.capabilities.get("ship_class", "small")
        existing = journal.count_ships()
        hull = f"H{existing + 1:04d}"
        ship_id = journal.create_ship(
            site_id=site_id,
            hull_number=hull,
            sku=sku.sku,
            ship_class=ship_class,
        )
        result.update(
            {"ship_id": ship_id, "hull_number": hull, "site_id": site_id}
        )
    elif sku.category == "ground_station":
        new_tier = sku.capabilities.get("ground_station_tier", "none")
        site_id = p["target_site_id"]
        current = journal.get_site_ground_station(site_id)
        gs_rank = {
            "none": 0,
            "portable": 1,
            "fixed_small": 2,
            "fixed_medium": 3,
            "deep_space": 4,
            "phased_array": 5,
        }
        if gs_rank.get(new_tier, 0) > gs_rank.get(current, 0):
            journal.set_site_ground_station(site_id, new_tier)
            result.update(
                {"site_id": site_id, "before": current, "after": new_tier}
            )
        else:
            result.update(
                {
                    "site_id": site_id,
                    "before": current,
                    "after": current,
                    "note": f"no upgrade (current {current} >= new {new_tier})",
                }
            )
    elif sku.category == "satellite":
        payload_type = sku.capabilities.get("payload", "comms")
        existing_count = journal.count_satellites()
        prefix = "SCP-OTV" if payload_type == "otv" else "SCP-SAT"
        callsign = f"{prefix}-{existing_count + 1:03d}"
        sat_id = journal.create_satellite(
            callsign=callsign,
            sku=sku.sku,
            satellite_class=sku.capabilities.get("satellite_class", "cubesat"),
            orbit=sku.capabilities.get("orbit", "LEO"),
            payload=payload_type,
        )
        result.update({"satellite_id": sat_id, "callsign": callsign})
    elif sku.category == "submarine":
        site_id = p["target_site_id"]
        sub_class = sku.capabilities.get("sub_class", "uuv")
        existing = journal.count_submarines()
        hull = f"SS{existing + 1:04d}"
        sub_id = journal.create_submarine(
            site_id=site_id,
            hull_number=hull,
            sku=sku.sku,
            sub_class=sub_class,
        )
        result.update(
            {"submarine_id": sub_id, "hull_number": hull, "site_id": site_id}
        )
    elif sku.category == "power_plant":
        site_id = p["target_site_id"]
        plant_type = sku.capabilities.get("plant_type", "genset")
        kw = int(sku.capabilities.get("kw_rating", 0))
        plant_id = journal.create_power_plant(
            site_id=site_id,
            sku=sku.sku,
            plant_type=plant_type,
            kw_rating=kw,
        )
        result.update(
            {
                "power_plant_id": plant_id,
                "site_id": site_id,
                "plant_type": plant_type,
                "kw_rating": kw,
            }
        )
    elif sku.category == "battery_bank":
        site_id = p["target_site_id"]
        kwh = float(sku.capabilities.get("battery_kwh", 0))
        journal.add_site_battery(site_id, kwh)
        res = journal.get_site_resilience(site_id)
        result.update(
            {"site_id": site_id, "added_kwh": kwh, "total_kwh": res["battery_kwh"]}
        )
    elif sku.category == "fuel_storage":
        site_id = p["target_site_id"]
        hrs = float(sku.capabilities.get("fuel_hours", 0))
        journal.add_site_fuel(site_id, hrs)
        res = journal.get_site_resilience(site_id)
        result.update(
            {"site_id": site_id, "added_hours": hrs, "total_hours": res["fuel_hours"]}
        )
    elif sku.category == "storage_array":
        site_id = p["target_site_id"]
        cap_gb = float(sku.capabilities.get("capacity_gb", 0))
        array_type = str(sku.capabilities.get("array_type", "ssd"))
        array_id = journal.create_storage_array(
            site_id=site_id, sku=sku.sku, capacity_gb=cap_gb, array_type=array_type,
        )
        result.update(
            {"storage_array_id": array_id, "site_id": site_id,
             "capacity_gb": cap_gb, "array_type": array_type}
        )
    elif sku.category == "tape_library":
        site_id = p["target_site_id"]
        cap_gb = float(sku.capabilities.get("capacity_gb", 0))
        lib_id = journal.create_tape_library(
            site_id=site_id, sku=sku.sku, capacity_gb=cap_gb,
        )
        result.update(
            {"tape_library_id": lib_id, "site_id": site_id, "capacity_gb": cap_gb}
        )
    elif sku.category == "pump_system":
        site_id = p["target_site_id"]
        cap = str(sku.capabilities.get("capacity", "small"))
        redundant = bool(sku.capabilities.get("redundant", False))
        pump_id = journal.create_pump(
            site_id=site_id, sku=sku.sku, capacity=cap, redundant=redundant,
        )
        result.update(
            {"pump_id": pump_id, "site_id": site_id,
             "capacity": cap, "redundant": redundant}
        )
    elif sku.category == "cooling_unit":
        site_id = p["target_site_id"]
        kw = int(sku.capabilities.get("kw_rating", 0))
        ctype = str(sku.capabilities.get("cooling_type", "crac"))
        unit_id = journal.create_cooling_unit(
            site_id=site_id, sku=sku.sku, kw_rating=kw, cooling_type=ctype,
        )
        result.update(
            {"cooling_unit_id": unit_id, "site_id": site_id,
             "kw_rating": kw, "cooling_type": ctype}
        )
    elif sku.category == "compute_module":
        # Compound asset: unpack a bundle of hosts + cooling into the
        # target site. Each host gets its own VM seeded with the
        # bundle's auto_vm_spec (or the generic seed).
        site_id = int(p["target_site_id"])
        bundle = sku.capabilities.get("bundle") or []
        installed_hosts: list[int] = []
        installed_vms: list[int] = []
        installed_cooling: list[int] = []
        for entry in bundle:
            kind = str(entry.get("kind", ""))
            count = int(entry.get("count", 1))
            if kind == "host":
                host_class = str(entry.get("host_class", "server"))
                host_specs = dict(entry.get("specs", {}) or {})
                avs = entry.get("auto_vm_spec")
                if isinstance(avs, dict) and avs:
                    host_specs["auto_vm_spec"] = dict(avs)
                name_prefix = str(entry.get("name_prefix", "node"))
                for i in range(count):
                    hid = journal.create_host(
                        site_id=site_id,
                        name=f"{name_prefix}-{sku.sku}-{purchase_id}-{i + 1:02d}",
                        host_class=host_class,
                        specs=dict(host_specs),
                        status="clean",
                    )
                    vm_spec = (
                        dict(host_specs["auto_vm_spec"])
                        if "auto_vm_spec" in host_specs
                        else seed_vm_spec().to_dict()
                    )
                    vid = journal.create_vm(
                        host_id=hid,
                        name=f"vm-{hid}-01",
                        spec=vm_spec,
                        status="idle",
                    )
                    installed_hosts.append(hid)
                    installed_vms.append(vid)
            elif kind == "cooling":
                kw = int(entry.get("kw", 0))
                ctype = str(entry.get("ctype", "crac"))
                sku_tag = str(entry.get("sku_tag", f"{ctype}-{kw}kw"))
                for _ in range(count):
                    cid = journal.create_cooling_unit(
                        site_id=site_id, sku=sku_tag,
                        kw_rating=kw, cooling_type=ctype,
                    )
                    installed_cooling.append(cid)
            else:
                # unknown bundle kind — skip quietly, surface in result
                result.setdefault("skipped_bundle_entries", []).append(entry)
        # Optional: bump the site's cooling capacity to reflect integrated
        # cooling that doesn't fit the per-unit model cleanly.
        bonus_kw = int(sku.capabilities.get("site_cooling_kw_bonus", 0) or 0)
        if bonus_kw:
            # Read current, add. Safe because set_site_capacity takes full values.
            from .procurement import site_utilization as _su  # local to avoid cycle
            current = _su(journal, site_id)
            new_cooling_cap = int(current.get("cooling_kw_capacity", 0)) + bonus_kw
            journal.set_site_capacity(
                site_id,
                power_kw=int(current.get("power_kw_capacity", 0)),
                cooling_kw=new_cooling_cap,
            )
            result["site_cooling_kw_bonus"] = bonus_kw
        result.update({
            "site_id": site_id,
            "hosts": installed_hosts,
            "vms": installed_vms,
            "cooling_units": installed_cooling,
            "host_count": len(installed_hosts),
            "vm_count": len(installed_vms),
        })

    elif sku.category == "host_containment_module":
        # Upgrade a host's baseline containment AND every VM currently on
        # it. This is the Faraday/mnestic/SCSC tier — one purchase
        # raises the entire rack's containment for that component.
        host_id = int(p["target_vm_id"])
        host = journal.get_host(host_id)
        if not host:
            result["error"] = f"target host {host_id} no longer exists"
        else:
            comp = str(sku.capabilities.get("vm_component", ""))
            value = int(sku.capabilities.get("value", 0))
            specs = dict(host["specs"])
            avs = dict(specs.get("auto_vm_spec") or {})
            before_base = int(avs.get(comp, 0))
            new_base = max(before_base, value)
            avs[comp] = new_base
            specs["auto_vm_spec"] = avs
            journal.update_host_specs(host_id, specs)
            updated_vms = []
            for v in journal.list_vms():
                if v["host_id"] != host_id:
                    continue
                vspec = dict(v["spec"])
                before_v = int(vspec.get(comp, 0))
                if before_v < new_base:
                    vspec[comp] = new_base
                    journal.update_vm_spec(v["id"], vspec)
                    updated_vms.append({
                        "vm_id": v["id"], "before": before_v, "after": new_base,
                    })
            result.update({
                "host_id": host_id,
                "component": comp,
                "host_baseline_before": before_base,
                "host_baseline_after": new_base,
                "vms_updated": updated_vms,
            })

    elif sku.category == "host_module":
        # target_vm_id carries the host id for host_module purchases.
        host_id = int(p["target_vm_id"])
        host = journal.get_host(host_id)
        if not host:
            result["error"] = f"target host {host_id} no longer exists"
        else:
            spec_key = str(sku.capabilities.get("host_spec", ""))
            add = int(sku.capabilities.get("add", 0))
            specs = dict(host["specs"])
            # Normalize to *_gb keys for RAM and storage_gb; older rows may
            # have storage_tb — migrate in-place.
            if spec_key == "storage_gb" and "storage_tb" in specs and "storage_gb" not in specs:
                specs["storage_gb"] = int(specs.pop("storage_tb")) * 1_000
            before = int(specs.get(spec_key, 0))
            specs[spec_key] = before + add
            journal.update_host_specs(host_id, specs)
            result.update(
                {"host_id": host_id, "spec": spec_key, "before": before,
                 "after": specs[spec_key], "add": add}
            )
    else:
        result["error"] = f"unsupported sku category {sku.category}"

    journal.mark_purchase_installed(purchase_id)
    journal.append("install_complete", "INFO", result)
    return result


def site_utilization(journal: Journal, site_id: int) -> dict:
    """Sum power draw and heat across all hosts assigned to a site.
    Genset-dependent sites without active diesel supply report effective
    power_kw_capacity=0, which marks them over budget and triggers brownouts.
    """
    from . import sites as site_catalog

    hosts = [h for h in journal.list_hosts() if h["site_id"] == site_id]
    total_w = sum(int(h.get("specs", {}).get("power_w", 0)) for h in hosts)
    total_btu = sum(int(h.get("specs", {}).get("heat_btu_hr", 0)) for h in hosts)
    capacity = journal.get_site_capacity(site_id) or {
        "power_kw": 0,
        "cooling_kw": 0,
    }

    # Base capacity + online power plants at this site
    plant_kw = journal.sum_site_power_plants_kw(site_id)
    effective_power_cap = int(capacity["power_kw"]) + plant_kw
    fuel_starved = False
    outaged = False
    flooded = False
    if site_catalog.site_requires_diesel(journal, site_id):
        active_diesel = [
            c for c in journal.list_contracts(
                status="active", contract_type="diesel_supply"
            )
            if c["target_site_id"] == site_id
        ]
        if not active_diesel:
            effective_power_cap = 0
            fuel_starved = True
    if site_catalog.site_requires_pumps(journal, site_id):
        pump_count = journal.count_site_pumps(site_id)
        if pump_count == 0:
            effective_power_cap = 0
            flooded = True
    # Active grid_power outage at site → capacity drops to 0 unless resilience
    # (batteries + fuel) was sufficient to ride through on event arrival.
    active = journal.active_outages(site_id=site_id)
    for o in active:
        if o["kind"] == "grid_power" and not o["ride_through"]:
            effective_power_cap = 0
            outaged = True
            break

    power_kw_used = round(total_w / 1000, 2)
    cooling_kw_used = round(total_btu / 3412, 2)
    # Installed cooling units stack onto the site-type base cooling budget.
    cooling_units_kw = journal.sum_site_cooling_units_kw(site_id)
    effective_cooling_cap = int(capacity["cooling_kw"]) + cooling_units_kw
    resilience = journal.get_site_resilience(site_id)
    ride_through_h = 0.0
    if power_kw_used > 0:
        ride_through_h = (
            resilience["battery_kwh"] / power_kw_used
            + resilience["fuel_hours"]
        )

    # Storage / tape accounting.
    host_storage_gb = 0.0
    for h in hosts:
        specs = h.get("specs", {})
        if "storage_gb" in specs:
            host_storage_gb += float(specs["storage_gb"])
        elif "storage_tb" in specs:
            host_storage_gb += float(specs["storage_tb"]) * 1_000
    array_storage_gb = journal.sum_site_storage_arrays_gb(site_id)
    storage_cap_gb = host_storage_gb + array_storage_gb
    storage_used_gb = journal.sum_site_storage_used_gb(site_id)

    # RAM totals across hosts at this site (not yet enforced against items)
    ram_cap_gb = sum(int(h.get("specs", {}).get("ram_gb", 0)) for h in hosts)

    tape_cap_gb = journal.sum_site_tape_libraries_gb(site_id)
    tape_used_gb = journal.sum_site_tape_used_gb(site_id)

    return {
        "site_id": site_id,
        "hosts": len(hosts),
        "power_w": total_w,
        "power_kw_used": power_kw_used,
        "power_kw_capacity": effective_power_cap,
        "power_kw_nominal": int(capacity["power_kw"]),
        "power_kw_plants": plant_kw,
        "power_over": power_kw_used > effective_power_cap,
        "fuel_starved": fuel_starved,
        "flooded": flooded,
        "outaged": outaged,
        "battery_kwh": resilience["battery_kwh"],
        "fuel_hours": resilience["fuel_hours"],
        "ride_through_hours": round(ride_through_h, 2),
        "heat_btu_hr": total_btu,
        "cooling_kw_used": cooling_kw_used,
        "cooling_kw_capacity": effective_cooling_cap,
        "cooling_kw_nominal": int(capacity["cooling_kw"]),
        "cooling_kw_units": cooling_units_kw,
        "cooling_over": cooling_kw_used > effective_cooling_cap,
        "ram_cap_gb": ram_cap_gb,
        "storage_cap_gb": round(storage_cap_gb, 1),
        "storage_used_gb": round(storage_used_gb, 1),
        "storage_over": storage_used_gb > storage_cap_gb,
        "tape_cap_gb": round(tape_cap_gb, 1),
        "tape_used_gb": round(tape_used_gb, 1),
        "tape_over": tape_used_gb > tape_cap_gb,
    }
