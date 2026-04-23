from __future__ import annotations

import os
from dataclasses import dataclass, field


_TS = float(os.environ.get("SCP_TIME_SCALE", "1.0"))


def _d(seconds: float) -> float:
    return seconds * _TS


@dataclass(frozen=True)
class Sku:
    sku: str
    name: str
    category: str           # server | aipod | mainframe | vm_module
    price_usd: int
    power_w: int
    form_factor: str
    lead_time_s: float      # already scaled by SCP_TIME_SCALE
    capabilities: dict = field(default_factory=dict)
    description: str = ""

    @property
    def heat_btu_hr(self) -> int:
        return round(self.power_w * 3.41)

    def to_dict(self) -> dict:
        return {
            "sku": self.sku,
            "name": self.name,
            "category": self.category,
            "price_usd": self.price_usd,
            "power_w": self.power_w,
            "heat_btu_hr": self.heat_btu_hr,
            "form_factor": self.form_factor,
            "lead_time_s": self.lead_time_s,
            "capabilities": self.capabilities,
            "description": self.description,
        }


SKUS: dict[str, Sku] = {}


def _add(s: Sku) -> None:
    SKUS[s.sku] = s


# --- Host-class SKUs (purchase creates a new host + default VM) --------

_add(Sku(
    "generic-1u-server", "Generic 1U server", "server",
    price_usd=8_000, power_w=400, form_factor="rack_u:1",
    lead_time_s=_d(3600),
    capabilities={
        "host_class": "server",
        "cpu_threads": 32,
        "ram_gb": 64,
        "storage_gb": 4_000,         # 4 TB NVMe baseline
    },
    description="Entry-level 1U rack server. 64 GB RAM, 4 TB NVMe.",
))
_add(Sku(
    "generic-2u-server", "Generic 2U server", "server",
    price_usd=18_000, power_w=800, form_factor="rack_u:2",
    lead_time_s=_d(3600),
    capabilities={
        "host_class": "server",
        "cpu_threads": 64,
        "ram_gb": 256,
        "storage_gb": 24_000,        # 24 TB mixed
    },
    description="Mid-tier 2U server. 256 GB RAM, 24 TB storage.",
))
_add(Sku(
    "container-compute-20ft", "20-ft compute container", "compute_module",
    price_usd=500_000, power_w=25_000, form_factor="iso_container:20",
    lead_time_s=_d(86_400 * 60),
    capabilities={
        "host_class": "server",
        "bundle": [
            {
                "kind": "host", "count": 4, "host_class": "server",
                "name_prefix": "node",
                "specs": {
                    "cpu_threads": 128,
                    "ram_gb": 512,
                    "storage_gb": 25_000,   # 25 TB each → 100 TB total
                    "power_w": 5_500,
                    "heat_btu_hr": 18_750,
                },
            },
            {
                "kind": "cooling", "count": 2, "ctype": "rdhx",
                "kw": 40, "sku_tag": "container-rdhx-40kw",
            },
        ],
        "site_cooling_kw_bonus": 80,
    },
    description=(
        "Self-contained 20-ft ISO compute container. Unpacks to 4 × 512 GB "
        "server nodes (each with its own VM) + 2 RDHX cooling blocks on-site."
    ),
))
_add(Sku(
    "container-compute-20ft-hs", "20-ft high-security compute container",
    "compute_module",
    price_usd=1_800_000, power_w=28_000, form_factor="iso_container:20",
    lead_time_s=_d(86_400 * 120),
    capabilities={
        "host_class": "server",
        "bundle": [
            {
                "kind": "host", "count": 4, "host_class": "server",
                "name_prefix": "hs-node",
                "specs": {
                    "cpu_threads": 128,
                    "ram_gb": 512,
                    "storage_gb": 25_000,
                    "power_w": 6_500,
                    "heat_btu_hr": 22_175,
                },
                # Per-VM baseline: hardware mem-enc 6 + bare-metal iso 5 +
                # mnestic fw 4 + polarized shielding 4 + live scanner 2 = 21
                "auto_vm_spec": {
                    "memory_encryption": 6,
                    "isolation": 5,
                    "mnestic_firmware": 4,
                    "physical_shielding": 4,
                    "scanner_freshness": 2,
                },
            },
            {
                "kind": "cooling", "count": 2, "ctype": "rdhx",
                "kw": 40, "sku_tag": "container-hs-rdhx-40kw",
            },
        ],
        "site_cooling_kw_bonus": 80,
    },
    description=(
        "Hardened 20-ft ISO container — 4 × 512 GB servers pre-sealed in "
        "Faraday + polarized shielding, mnestic firmware, hardware memory "
        "encryption, bare-metal isolation. Every VM starts at containment 21 "
        "out of the box — Euclid-ready on delivery."
    ),
))
_add(Sku(
    "invidia-dgz-pod", "Invidia DGZ pod (8x I300 Blackhall)", "aipod",
    price_usd=2_400_000, power_w=10_000, form_factor="rack_u:8",
    lead_time_s=_d(86_400 * 7),
    capabilities={
        "host_class": "aipod",
        "ai_accel": "I300",
        "count": 8,
        "ram_gb": 1_024,
        "storage_gb": 100_000,       # 100 TB fast scratch
        "analysis_speedup": 2.0,
    },
    description="Containerized AI training pod; halves analyze duration.",
))
_add(Sku(
    "ibex-z-base", "Ibex Z-class (base)", "mainframe",
    price_usd=3_500_000, power_w=12_000, form_factor="rack_u:20",
    lead_time_s=_d(86_400 * 14),
    capabilities={
        "host_class": "mainframe",
        "ram_gb": 2_048,
        "storage_gb": 50_000,        # 50 TB mainframe DASD
        "max_lpars": 10,
        "auto_vm_spec": {
            "memory_encryption": 10,
            "isolation": 8,
            "mnestic_firmware": 4,
            "physical_shielding": 6,
            "scanner_freshness": 2,
        },
    },
    description="Mainframe with encrypted-memory LPARs. Seed LPAR containment=30.",
))

# --- Panthalassa subsea products (ideal for subsea_pod sites) --------

_add(Sku(
    "panthalassa-core", "Panthalassa Core pod (subsea compute)",
    "compute_module",
    price_usd=10_000_000, power_w=3_000, form_factor="subsea_capsule",
    lead_time_s=_d(86_400 * 90),
    capabilities={
        "host_class": "server",
        "recommended_site_type": "subsea_pod",
        "bundle": [
            {
                "kind": "host", "count": 4, "host_class": "server",
                "name_prefix": "panth-node",
                "specs": {
                    "cpu_threads": 128,
                    "ram_gb": 512,
                    "storage_gb": 12_000,
                    "power_w": 600,
                    "heat_btu_hr": 2_046,
                    "seawater_cooled": True,
                },
                # Seawater housing adds physical shielding out of the box
                "auto_vm_spec": {
                    "memory_encryption": 3,
                    "isolation": 2,
                    "mnestic_firmware": 0,
                    "physical_shielding": 4,  # pressure-hull + EM shielding
                    "scanner_freshness": 1,
                },
            },
            {
                "kind": "cooling", "count": 2, "ctype": "seawater_loop",
                "kw": 60, "sku_tag": "panthalassa-seawater-loop",
            },
        ],
        "site_cooling_kw_bonus": 120,
    },
    description=(
        "Subsea capsule, seawater-cooled. Unpacks to 4 × 512 GB nodes (each "
        "with its own VM, baseline containment 10 from pressure-hull EM "
        "shielding) + 2 seawater cooling loops. Ideal at subsea_pod sites."
    ),
))
_add(Sku(
    "panthalassa-array", "Panthalassa Array (subsea compute cluster)",
    "compute_module",
    price_usd=45_000_000, power_w=12_000, form_factor="subsea_capsule",
    lead_time_s=_d(86_400 * 180),
    capabilities={
        "host_class": "server",
        "recommended_site_type": "subsea_pod",
        "bundle": [
            {
                "kind": "host", "count": 8, "host_class": "server",
                "name_prefix": "panth-array-node",
                "specs": {
                    "cpu_threads": 256,
                    "ram_gb": 1_024,
                    "storage_gb": 25_000,
                    "power_w": 1_400,
                    "heat_btu_hr": 4_774,
                    "seawater_cooled": True,
                },
                "auto_vm_spec": {
                    "memory_encryption": 3,
                    "isolation": 2,
                    "mnestic_firmware": 0,
                    "physical_shielding": 4,
                    "scanner_freshness": 1,
                },
            },
            {
                "kind": "cooling", "count": 4, "ctype": "seawater_loop",
                "kw": 80, "sku_tag": "panthalassa-array-seawater-loop",
            },
        ],
        "site_cooling_kw_bonus": 320,
    },
    description=(
        "Large subsea cluster capsule. Unpacks to 8 × 1 TB nodes (each with "
        "its own VM, baseline containment 10) + 4 seawater cooling loops. "
        "Full-rack compute under seawater."
    ),
))
_add(Sku(
    "panthalassa-vault", "Panthalassa Vault (subsea cold archive)", "server",
    price_usd=20_000_000, power_w=500, form_factor="subsea_capsule",
    lead_time_s=_d(86_400 * 120),
    capabilities={
        "host_class": "server",
        "cpu_threads": 16,
        "ram_gb": 64,
        "storage_pb": 4,
        "seawater_cooled": True,
        "recommended_site_type": "subsea_pod",
    },
    description="4 PB subsea cold-storage capsule. Ultra-low-power archival.",
))

# --- Power plants (add capacity to a site) ---------------------------

_add(Sku(
    "diesel-genset-sm", "Small diesel genset (20 kW)", "power_plant",
    price_usd=30_000, power_w=0, form_factor="trailer",
    lead_time_s=_d(86_400 * 3),
    capabilities={"plant_type": "genset", "kw_rating": 20},
    description="Trailer-mounted 20 kW genset. Needs diesel_supply contract.",
))
_add(Sku(
    "diesel-genset-md", "Medium diesel genset (100 kW)", "power_plant",
    price_usd=150_000, power_w=0, form_factor="container",
    lead_time_s=_d(86_400 * 10),
    capabilities={"plant_type": "genset", "kw_rating": 100},
    description="Containerized 100 kW genset.",
))
_add(Sku(
    "diesel-genset-lg", "Large diesel genset (500 kW)", "power_plant",
    price_usd=800_000, power_w=0, form_factor="facility",
    lead_time_s=_d(86_400 * 30),
    capabilities={"plant_type": "genset", "kw_rating": 500},
    description="Building-scale 500 kW prime-power genset.",
))
_add(Sku(
    "solar-array-sm", "Small solar + battery (10 kW)", "power_plant",
    price_usd=40_000, power_w=0, form_factor="array",
    lead_time_s=_d(86_400 * 14),
    capabilities={"plant_type": "solar", "kw_rating": 10},
    description="PV + LFP battery. Good for ARM field nodes.",
))
_add(Sku(
    "solar-array-lg", "Large solar + battery (100 kW)", "power_plant",
    price_usd=500_000, power_w=0, form_factor="array",
    lead_time_s=_d(86_400 * 45),
    capabilities={"plant_type": "solar", "kw_rating": 100},
    description="Utility-scale PV + LFP. Daytime-dominant power.",
))
_add(Sku(
    "kilopower-micro", "Kilopower micro-reactor (10 kW)", "power_plant",
    price_usd=15_000_000, power_w=0, form_factor="truck_portable",
    lead_time_s=_d(86_400 * 180),
    capabilities={
        "plant_type": "microreactor",
        "kw_rating": 10,
        "requires_licensed_ops": 2,
    },
    description="10-year fuel. Requires 2 licensed reactor operators.",
))
_add(Sku(
    "evinci-mobile-smr", "Mobile SMR (5 MW)", "power_plant",
    price_usd=120_000_000, power_w=0, form_factor="container",
    lead_time_s=_d(86_400 * 730),
    capabilities={
        "plant_type": "smr",
        "kw_rating": 5_000,
        "requires_licensed_ops": 4,
    },
    description="eVinci-class mobile SMR. 3-7 yr fuel. 4 operators + support staff.",
))
_add(Sku(
    "nuscale-smr", "Deployable SMR (50 MW)", "power_plant",
    price_usd=700_000_000, power_w=0, form_factor="facility",
    lead_time_s=_d(86_400 * 1095),
    capabilities={
        "plant_type": "smr",
        "kw_rating": 50_000,
        "requires_licensed_ops": 12,
        "passive_safety": False,
    },
    description="NuScale-class deployable SMR. Months to stand up on-site.",
))
_add(Sku(
    "msr-micro", "Molten-salt micro-reactor (5 MW, Gen-IV)", "power_plant",
    price_usd=180_000_000, power_w=0, form_factor="container",
    lead_time_s=_d(86_400 * 900),
    capabilities={
        "plant_type": "msr",
        "kw_rating": 5_000,
        "requires_licensed_ops": 4,
        "passive_safety": True,
        "atmospheric_pressure": True,
    },
    description=(
        "Liquid molten-salt Gen-IV. Freeze-plug drains to passive-cooling tank "
        "on fault — no steam, no high-pressure loop. Safer than PWR SMRs."
    ),
))
_add(Sku(
    "msr-smr", "Molten-salt SMR (100 MW, Gen-IV)", "power_plant",
    price_usd=900_000_000, power_w=0, form_factor="facility",
    lead_time_s=_d(86_400 * 1460),
    capabilities={
        "plant_type": "msr",
        "kw_rating": 100_000,
        "requires_licensed_ops": 10,
        "passive_safety": True,
        "atmospheric_pressure": True,
    },
    description=(
        "Grid-scale molten-salt SMR. Higher thermal efficiency; actinide-burner "
        "option. Inherent passive safety."
    ),
))

# --- Backup batteries (UPS + bank tiers) -----------------------------

_add(Sku(
    "ups-rack", "Rack UPS (5 kWh)", "battery_bank",
    price_usd=8_000, power_w=0, form_factor="rack_u:2",
    lead_time_s=_d(86_400 * 2),
    capabilities={"battery_kwh": 5},
    description="Rack UPS; short ride-through for orderly shutdown.",
))
_add(Sku(
    "ups-room", "Room UPS (50 kWh LFP)", "battery_bank",
    price_usd=80_000, power_w=0, form_factor="rack_u:12",
    lead_time_s=_d(86_400 * 10),
    capabilities={"battery_kwh": 50},
    description="LFP room-scale UPS. Hours of ride-through at typical loads.",
))
_add(Sku(
    "battery-bank-200", "LFP bank (200 kWh)", "battery_bank",
    price_usd=180_000, power_w=0, form_factor="container",
    lead_time_s=_d(86_400 * 21),
    capabilities={"battery_kwh": 200},
    description="Containerized LFP bank. Pairs with solar arrays.",
))
_add(Sku(
    "battery-bank-1000", "Grid-scale LFP (1 MWh)", "battery_bank",
    price_usd=700_000, power_w=0, form_factor="facility",
    lead_time_s=_d(86_400 * 60),
    capabilities={"battery_kwh": 1000},
    description="Utility-scale battery. Rides through multi-hour grid outages.",
))

# --- Fuel storage (extends genset runtime during supply disruptions) --

_add(Sku(
    "fuel-tank-small", "Fuel tank (24h reserve at nominal load)", "fuel_storage",
    price_usd=12_000, power_w=0, form_factor="tank",
    lead_time_s=_d(86_400 * 3),
    capabilities={"fuel_hours": 24},
    description="Above-ground 1,000 L diesel tank. 24h at nominal site draw.",
))
_add(Sku(
    "fuel-tank-med", "Fuel tank (72h reserve)", "fuel_storage",
    price_usd=40_000, power_w=0, form_factor="tank",
    lead_time_s=_d(86_400 * 10),
    capabilities={"fuel_hours": 72},
    description="3-day diesel storage. Double-walled, bunded.",
))
_add(Sku(
    "fuel-reserve-underground", "Underground fuel reserve (30 days)", "fuel_storage",
    price_usd=350_000, power_w=0, form_factor="facility",
    lead_time_s=_d(86_400 * 45),
    capabilities={"fuel_hours": 720},
    description="Buried reserve sufficient for month-long supply disruptions.",
))

# --- Storage arrays (hot working storage for quarantined items) ------

_add(Sku(
    "storage-array-48tb-ssd", "48 TB SSD array", "storage_array",
    price_usd=15_000, power_w=300, form_factor="rack_u:2",
    lead_time_s=_d(86_400 * 5),
    capabilities={"capacity_gb": 48_000, "array_type": "ssd"},
    description="All-flash quarantine storage. Low latency for active analysis.",
))
_add(Sku(
    "storage-array-500tb-hdd", "500 TB HDD array", "storage_array",
    price_usd=120_000, power_w=2_000, form_factor="rack_u:12",
    lead_time_s=_d(86_400 * 14),
    capabilities={"capacity_gb": 500_000, "array_type": "hdd"},
    description="Bulk spinning-disk array. Large quarantine pool.",
))
_add(Sku(
    "storage-array-5pb-hybrid", "5 PB hybrid array", "storage_array",
    price_usd=900_000, power_w=8_000, form_factor="rack_u:48",
    lead_time_s=_d(86_400 * 45),
    capabilities={"capacity_gb": 5_000_000, "array_type": "hybrid"},
    description="SSD cache + HDD bulk. Enterprise-tier working storage.",
))
_add(Sku(
    "container-storage-20ft", "20-ft storage container (10 PB hybrid)", "storage_array",
    price_usd=400_000, power_w=4_000, form_factor="iso_container:20",
    lead_time_s=_d(86_400 * 60),
    capabilities={"capacity_gb": 10_000_000, "array_type": "hybrid"},
    description="Self-contained 20-ft ISO storage container. Ships + cabled on-site.",
))

# --- Tape libraries (cold archive for archived items) ----------------

_add(Sku(
    "tape-lib-small", "Small tape library (500 TB LTO)", "tape_library",
    price_usd=25_000, power_w=400, form_factor="rack_u:8",
    lead_time_s=_d(86_400 * 10),
    capabilities={"capacity_gb": 500_000},
    description="Automated LTO library. Basic cold-archive capacity.",
))
_add(Sku(
    "tape-lib-med", "Mid tape library (5 PB)", "tape_library",
    price_usd=200_000, power_w=2_500, form_factor="rack_u:20",
    lead_time_s=_d(86_400 * 30),
    capabilities={"capacity_gb": 5_000_000},
    description="Multi-drawer tape library. Scales to petabytes.",
))
_add(Sku(
    "tape-lib-vault", "Archive vault (50 PB)", "tape_library",
    price_usd=1_800_000, power_w=15_000, form_factor="facility",
    lead_time_s=_d(86_400 * 180),
    capabilities={"capacity_gb": 50_000_000},
    description="Foundation-tier deep archive. Requires dedicated room.",
))

# --- Cooling units (add kW of heat rejection to a site) --------------
# Cooling equipment itself draws power (compressor/pump) — modeled via
# the SKU's power_w field, which flows through to host specs at install.
# Thermodynamics isn't precise here; kw_rating is the heat-rejection
# capacity the site gains.

_add(Sku(
    "cooling-crac-20kw", "CRAC unit (20 kW air cooling)", "cooling_unit",
    price_usd=15_000, power_w=6_000, form_factor="floor",
    lead_time_s=_d(86_400 * 5),
    capabilities={"kw_rating": 20, "cooling_type": "crac"},
    description="Computer-room air conditioner. Cheap, low-density baseline.",
))
_add(Sku(
    "cooling-rdhx-50kw", "Rear-door heat exchanger (50 kW per rack)", "cooling_unit",
    price_usd=50_000, power_w=3_000, form_factor="rack_door",
    lead_time_s=_d(86_400 * 14),
    capabilities={"kw_rating": 50, "cooling_type": "rdhx"},
    description="Passive-fan RDHX bolts to rack rear. Higher density than CRAC.",
))
_add(Sku(
    "cooling-chiller-200kw", "Chiller plant (200 kW)", "cooling_unit",
    price_usd=250_000, power_w=40_000, form_factor="facility",
    lead_time_s=_d(86_400 * 30),
    capabilities={"kw_rating": 200, "cooling_type": "chiller"},
    description="Room-scale chilled-water plant. Standard DC cooling.",
))
_add(Sku(
    "cooling-chiller-1mw", "Chiller plant (1 MW)", "cooling_unit",
    price_usd=1_200_000, power_w=180_000, form_factor="facility",
    lead_time_s=_d(86_400 * 90),
    capabilities={"kw_rating": 1_000, "cooling_type": "chiller"},
    description="Large DC plant chiller. Multi-row compute rooms.",
))
_add(Sku(
    "cooling-dlc-100kw", "Direct-liquid cooling (100 kW, per rack)", "cooling_unit",
    price_usd=180_000, power_w=12_000, form_factor="rack_u:full",
    lead_time_s=_d(86_400 * 21),
    capabilities={"kw_rating": 100, "cooling_type": "dlc"},
    description="In-rack cold-plate liquid loop. Needed for DGZ pods at density.",
))
_add(Sku(
    "cooling-immersion-50kw", "Immersion tank (50 kW, two-phase)", "cooling_unit",
    price_usd=80_000, power_w=5_000, form_factor="tank",
    lead_time_s=_d(86_400 * 30),
    capabilities={"kw_rating": 50, "cooling_type": "immersion"},
    description="Dielectric immersion. Extreme density; slow service access.",
))
_add(Sku(
    "cooling-immersion-250kw", "Immersion cluster (250 kW)", "cooling_unit",
    price_usd=380_000, power_w=22_000, form_factor="facility",
    lead_time_s=_d(86_400 * 60),
    capabilities={"kw_rating": 250, "cooling_type": "immersion"},
    description="Multi-tank immersion array. AI-training scale.",
))

# --- Dewatering pump systems (mandatory for underground sites) -------

_add(Sku(
    "pump-system-sm", "Dewatering pump system (small)", "pump_system",
    price_usd=50_000, power_w=5_000, form_factor="facility",
    lead_time_s=_d(86_400 * 7),
    capabilities={"capacity": "small", "redundant": False},
    description=(
        "Basic dewatering setup. One installed pump_system satisfies the "
        "pump requirement for underground sites."
    ),
))
_add(Sku(
    "pump-system-lg-redundant", "Dewatering pump system (N+1 redundant)", "pump_system",
    price_usd=200_000, power_w=20_000, form_factor="facility",
    lead_time_s=_d(86_400 * 30),
    capabilities={"capacity": "large", "redundant": True},
    description=(
        "Redundant N+1 pump array with backup power tie-in. Survives "
        "individual pump failures."
    ),
))

# --- Host modules (in-place RAM / storage upgrades per host) ---------

_add(Sku(
    "host-ram-64gb", "Host RAM upgrade (+64 GB DDR5)", "host_module",
    price_usd=2_000, power_w=10, form_factor="dimm",
    lead_time_s=_d(3600),
    capabilities={"host_spec": "ram_gb", "add": 64},
    description="DIMM kit. +64 GB RAM to target host.",
))
_add(Sku(
    "host-ram-512gb", "Host RAM upgrade (+512 GB DDR5)", "host_module",
    price_usd=15_000, power_w=60, form_factor="dimm",
    lead_time_s=_d(86_400 * 2),
    capabilities={"host_spec": "ram_gb", "add": 512},
    description="Full-channel memory expansion.",
))
_add(Sku(
    "host-ram-1tb", "Host RAM upgrade (+1 TB DDR5)", "host_module",
    price_usd=35_000, power_w=50, form_factor="dimm-bank",
    lead_time_s=_d(86_400 * 3),
    capabilities={"host_spec": "ram_gb", "add": 1_024},
    description=(
        "16×64 GB DIMM bank. Needed for parallel analysis of mid-Euclid "
        "items or a single large Euclid on a dedicated VM."
    ),
))
_add(Sku(
    "host-ram-2tb", "Host RAM upgrade (+2 TB DDR5)", "host_module",
    price_usd=80_000, power_w=100, form_factor="dimm-bank",
    lead_time_s=_d(86_400 * 7),
    capabilities={"host_spec": "ram_gb", "add": 2_048},
    description=(
        "Eight-channel workstation memory expansion. Enough for a single "
        "mid-tier Keter VM."
    ),
))
_add(Sku(
    "host-ram-4tb", "Host RAM upgrade (+4 TB DDR5)", "host_module",
    price_usd=200_000, power_w=200, form_factor="dimm-bank",
    lead_time_s=_d(86_400 * 14),
    capabilities={"host_spec": "ram_gb", "add": 4_096},
    description=(
        "Dual-socket server RAM ceiling. Fits most Keter items on a "
        "single VM without needing to split the host."
    ),
))
_add(Sku(
    "host-ram-cxl-8tb", "CXL memory fabric (+8 TB)", "host_module",
    price_usd=500_000, power_w=400, form_factor="cxl-fabric",
    lead_time_s=_d(86_400 * 21),
    capabilities={"host_spec": "ram_gb", "add": 8_192},
    description=(
        "CXL 3.0 memory-pool appliance. Requires a server or mainframe "
        "with CXL fabric; bulk-Keter capable."
    ),
))
_add(Sku(
    "host-ram-lpar-16tb", "Mainframe LPAR memory (+16 TB)", "host_module",
    price_usd=1_200_000, power_w=800, form_factor="lpar-bank",
    lead_time_s=_d(86_400 * 45),
    capabilities={"host_spec": "ram_gb", "add": 16_384},
    description=(
        "Mainframe-class LPAR memory bank. The only option for the largest "
        "Keter items (multi-TB) kept on a single VM. Long lead time."
    ),
))
_add(Sku(
    "host-storage-nvme-4tb", "NVMe storage (+4 TB)", "host_module",
    price_usd=1_500, power_w=15, form_factor="u.2",
    lead_time_s=_d(3600),
    capabilities={"host_spec": "storage_gb", "add": 4_000},
    description="PCIe NVMe drive.",
))
_add(Sku(
    "host-storage-hdd-48tb", "HDD storage (+48 TB)", "host_module",
    price_usd=18_000, power_w=80, form_factor="3.5in-bank",
    lead_time_s=_d(86_400 * 5),
    capabilities={"host_spec": "storage_gb", "add": 48_000},
    description="Bulk spinning-disk bank.",
))

# --- VM upgrade modules (apply to a specific VM) ----------------------

_add(Sku(
    "sev-crypto-card", "Hardware memory encryption card", "vm_module",
    price_usd=45_000, power_w=25, form_factor="pcie",
    lead_time_s=_d(3600),
    capabilities={"vm_component": "memory_encryption", "value": 6},
    description="AMD-SEV-analog card. Upgrades memory_encryption to 6.",
))
_add(Sku(
    "live-scanner-feed", "Live scanner signature feed subscription", "vm_module",
    price_usd=15_000, power_w=0, form_factor="subscription",
    lead_time_s=_d(60),
    capabilities={"vm_component": "scanner_freshness", "value": 2},
    description="Activates live signature feed. scanner_freshness=2.",
))
_add(Sku(
    "mnestic-firmware", "Mnestic-hardened firmware", "vm_module",
    price_usd=60_000, power_w=0, form_factor="software",
    lead_time_s=_d(14_400),
    capabilities={"vm_component": "mnestic_firmware", "value": 2},
    description="Firmware flash. Upgrades mnestic_firmware to 2.",
))
_add(Sku(
    "faraday-rack", "Faraday-shielded rack enclosure", "vm_module",
    price_usd=120_000, power_w=0, form_factor="rack_u:1",
    lead_time_s=_d(86_400 * 2),
    capabilities={"vm_component": "physical_shielding", "value": 2},
    description="EM-shielded enclosure. physical_shielding=2.",
))
_add(Sku(
    "scsc-room", "SCSC-hardened analysis room", "vm_module",
    price_usd=800_000, power_w=0, form_factor="facility",
    lead_time_s=_d(86_400 * 30),
    capabilities={"vm_component": "physical_shielding", "value": 6},
    description="SCSC-grade facility. physical_shielding=6.",
))

# --- Host-wide containment modules ------------------------------------
#
# These install against a HOST (not a single VM). One purchase raises the
# specified containment component for the host's baseline (auto_vm_spec)
# AND every VM currently running on that host. A fresh VM provisioned on
# the host afterwards inherits the new baseline automatically. Buys you
# rack-wide protection in one shot instead of per-VM retrofit.

_add(Sku(
    "host-faraday-cage", "Host-wide Faraday cage enclosure",
    "host_containment_module",
    price_usd=180_000, power_w=0, form_factor="rack_u:8",
    lead_time_s=_d(86_400 * 3),
    capabilities={"vm_component": "physical_shielding", "value": 2},
    description=(
        "EM-shielded rack-row enclosure. Bumps physical_shielding to 2 "
        "on the host AND every VM on it; new VMs inherit automatically."
    ),
))
_add(Sku(
    "host-polarized-shielding", "Host polarized shielding retrofit",
    "host_containment_module",
    price_usd=500_000, power_w=0, form_factor="rack_row",
    lead_time_s=_d(86_400 * 14),
    capabilities={"vm_component": "physical_shielding", "value": 4},
    description=(
        "Polarized optical + EM shielding for the full rack. "
        "physical_shielding=4 on host + all VMs."
    ),
))
_add(Sku(
    "host-scsc-vault", "Host SCSC-grade vault install",
    "host_containment_module",
    price_usd=1_400_000, power_w=0, form_factor="facility",
    lead_time_s=_d(86_400 * 45),
    capabilities={"vm_component": "physical_shielding", "value": 6},
    description=(
        "SCSC-class hardened vault around the entire host. "
        "physical_shielding=6 on host + all VMs."
    ),
))
_add(Sku(
    "host-mnestic-firmware", "Host-wide mnestic firmware package",
    "host_containment_module",
    price_usd=220_000, power_w=0, form_factor="software",
    lead_time_s=_d(86_400 * 2),
    capabilities={"vm_component": "mnestic_firmware", "value": 4},
    description=(
        "Firmware flash applied to host + every VM. "
        "mnestic_firmware=4 rack-wide."
    ),
))
_add(Sku(
    "host-hw-memenc", "Host-wide hardware memory encryption",
    "host_containment_module",
    price_usd=320_000, power_w=40, form_factor="rack_u:2",
    lead_time_s=_d(86_400 * 7),
    capabilities={"vm_component": "memory_encryption", "value": 6},
    description=(
        "SEV-class hardware crypto at the host level; every VM on the "
        "host gets memory_encryption=6."
    ),
))
_add(Sku(
    "host-bare-metal-isolation", "Host bare-metal isolation retrofit",
    "host_containment_module",
    price_usd=260_000, power_w=0, form_factor="software",
    lead_time_s=_d(86_400 * 5),
    capabilities={"vm_component": "isolation", "value": 5},
    description=(
        "Reconfigures the host + every VM to bare-metal partition mode. "
        "isolation=5 on all."
    ),
))

# --- Site encryption equipment (gates commercial-link data handling) --

_add(Sku(
    "wireshield-vpn", "WireShield software VPN", "site_encryption",
    price_usd=25_000, power_w=0, form_factor="software",
    lead_time_s=_d(3600),
    capabilities={"encryption_level": "software"},
    description="Software site VPN (WireGuard-analog). Adequate for Safe-class over commercial links.",
))
_add(Sku(
    "sentinel-vpn", "Sentinel hardware VPN appliance", "site_encryption",
    price_usd=150_000, power_w=80, form_factor="rack_u:1",
    lead_time_s=_d(86_400 * 7),
    capabilities={"encryption_level": "hardware"},
    description="Hardware IPsec appliance. Required for Euclid-class over commercial links.",
))
_add(Sku(
    "aegis-type1", "Aegis Type-1 link encryptor", "site_encryption",
    price_usd=800_000, power_w=120, form_factor="rack_u:1",
    lead_time_s=_d(86_400 * 30),
    capabilities={"encryption_level": "type1"},
    description="High-assurance Type-1 link encryptor. Required for Keter-class over commercial links.",
))

# --- Airfield infrastructure (site-level upgrade) ---------------------

_add(Sku(
    "dirt_strip", "Austere dirt airstrip", "airfield",
    price_usd=500_000, power_w=0, form_factor="facility",
    lead_time_s=_d(86_400 * 14),
    capabilities={"airfield_tier": "dirt_strip"},
    description="Seasonal gravel strip. Accepts light GA and helicopters.",
))
_add(Sku(
    "small_airport", "Small commercial airport build-out", "airfield",
    price_usd=15_000_000, power_w=20_000, form_factor="facility",
    lead_time_s=_d(86_400 * 180),
    capabilities={"airfield_tier": "small_airport"},
    description="Paved 1,500 m runway. Accepts medium cargo and biz jets.",
))
_add(Sku(
    "private_airfield", "Owned private airfield", "airfield",
    price_usd=80_000_000, power_w=50_000, form_factor="facility",
    lead_time_s=_d(86_400 * 365),
    capabilities={"airfield_tier": "private_airfield"},
    description="Full control, no public visibility. Paved 2,500 m runway.",
))

# --- Aircraft ---------------------------------------------------------

_add(Sku(
    "caesna-182", "Caesna 182 (GA)", "aircraft",
    price_usd=400_000, power_w=0, form_factor="aircraft",
    lead_time_s=_d(86_400 * 30),
    capabilities={
        "aircraft_class": "ga_single",
        "class_name": "fixed_wing",
        "min_airfield": "dirt_strip",
    },
    description="Single-engine GA. Commute / small-parcel runs.",
))
_add(Sku(
    "piperline-caravan", "Piperline Caravan", "aircraft",
    price_usd=2_500_000, power_w=0, form_factor="aircraft",
    lead_time_s=_d(86_400 * 45),
    capabilities={
        "aircraft_class": "light_cargo",
        "class_name": "fixed_wing",
        "min_airfield": "dirt_strip",
    },
    description="Single-turboprop utility. Austere-strip light cargo.",
))
_add(Sku(
    "lightfoot-407", "Lightfoot-407 (Bell 407-analog)", "aircraft",
    price_usd=4_000_000, power_w=0, form_factor="aircraft",
    lead_time_s=_d(86_400 * 60),
    capabilities={
        "aircraft_class": "light_heli",
        "class_name": "rotary",
        "min_airfield": "dirt_strip",
    },
    description="Light utility helicopter. Small team insertion.",
))
_add(Sku(
    "herald-class", "Herald-class (C-130J-analog)", "aircraft",
    price_usd=70_000_000, power_w=0, form_factor="aircraft",
    lead_time_s=_d(86_400 * 180),
    capabilities={
        "aircraft_class": "medium_cargo",
        "class_name": "fixed_wing",
        "min_airfield": "small_airport",
    },
    description="Austere-strip medium cargo. Slings MobiDC-sized payloads.",
))

# --- Aircraft: passenger / biz jets ----------------------------------

_add(Sku(
    "goldstream-g650", "Goldstream G650 (Gulfstream-analog)", "aircraft",
    price_usd=65_000_000, power_w=0, form_factor="aircraft",
    lead_time_s=_d(86_400 * 120),
    capabilities={
        "aircraft_class": "exec_jet",
        "class_name": "fixed_wing",
        "min_airfield": "small_airport",
    },
    description="Intercontinental exec jet. 8 pax, 13,000 km range.",
))
_add(Sku(
    "broadsword-global", "Broadsword Global (Bombardier-analog)", "aircraft",
    price_usd=75_000_000, power_w=0, form_factor="aircraft",
    lead_time_s=_d(86_400 * 150),
    capabilities={
        "aircraft_class": "exec_jet_secure",
        "class_name": "fixed_wing",
        "min_airfield": "small_airport",
    },
    description="Long-range biz jet w/ secure comms fit.",
))

# --- Aircraft: light utility / cargo ---------------------------------

_add(Sku(
    "twin-utility", "Twin Utility (Twin Otter-analog)", "aircraft",
    price_usd=8_000_000, power_w=0, form_factor="aircraft",
    lead_time_s=_d(86_400 * 60),
    capabilities={
        "aircraft_class": "stol_utility",
        "class_name": "fixed_wing",
        "min_airfield": "dirt_strip",
        "austere_capable": True,
    },
    description="Twin-turboprop STOL. Amphibious variant available for water sites.",
))
_add(Sku(
    "amphibian-cl415", "Amphibian CL-415-analog", "aircraft",
    price_usd=30_000_000, power_w=0, form_factor="aircraft",
    lead_time_s=_d(86_400 * 180),
    capabilities={
        "aircraft_class": "amphibian",
        "class_name": "fixed_wing",
        "min_airfield": "dirt_strip",
        "water_capable": True,
    },
    description="Amphibious fixed-wing. Water sites accessible without an airfield.",
))

# --- Aircraft: heavy cargo -------------------------------------------

_add(Sku(
    "a400m-bolder", "Bolderhaul-A400 (A400M-analog)", "aircraft",
    price_usd=150_000_000, power_w=0, form_factor="aircraft",
    lead_time_s=_d(86_400 * 270),
    capabilities={
        "aircraft_class": "medium_heavy_cargo",
        "class_name": "fixed_wing",
        "min_airfield": "small_airport",
    },
    description="37 t payload. MobiDC + outsized cargo on improved strips.",
))
_add(Sku(
    "titanlift-17", "Titanlift-17 (C-17 Globemaster-analog)", "aircraft",
    price_usd=250_000_000, power_w=0, form_factor="aircraft",
    lead_time_s=_d(86_400 * 365),
    capabilities={
        "aircraft_class": "strategic_cargo",
        "class_name": "fixed_wing",
        "min_airfield": "small_airport",
        "austere_capable": True,
    },
    description="77 t strategic lift. Carries a full MobiDC or disassembled SMR.",
))
_add(Sku(
    "galaxy-5", "Galaxy-5 (C-5 Galaxy-analog)", "aircraft",
    price_usd=300_000_000, power_w=0, form_factor="aircraft",
    lead_time_s=_d(86_400 * 400),
    capabilities={
        "aircraft_class": "outsized_strategic",
        "class_name": "fixed_wing",
        "min_airfield": "private_airfield",
    },
    description="130 t outsized cargo. Carries Typhoon sub sections, reactors.",
))

# --- Aircraft: maritime patrol + ISR (radar/ELINT/SIGINT/IMINT) ------

_add(Sku(
    "oceanhawk-mpa", "Oceanhawk MPA (P-8 Poseidon-analog)", "aircraft",
    price_usd=250_000_000, power_w=0, form_factor="aircraft",
    lead_time_s=_d(86_400 * 300),
    capabilities={
        "aircraft_class": "mpa_sigint",
        "class_name": "fixed_wing",
        "min_airfield": "small_airport",
        "isr_type": "sigint",
    },
    description="Maritime patrol + airborne SIGINT. +1 scan range per airframe.",
))
_add(Sku(
    "skywatch-awacs", "Skywatch AWACS (E-3 Sentry-analog)", "aircraft",
    price_usd=280_000_000, power_w=0, form_factor="aircraft",
    lead_time_s=_d(86_400 * 365),
    capabilities={
        "aircraft_class": "awacs",
        "class_name": "fixed_wing",
        "min_airfield": "small_airport",
        "isr_type": "radar",
    },
    description="Airborne early warning + battle management radar.",
))
_add(Sku(
    "rivergaze-rc135", "Rivergaze (RC-135-analog)", "aircraft",
    price_usd=320_000_000, power_w=0, form_factor="aircraft",
    lead_time_s=_d(86_400 * 365),
    capabilities={
        "aircraft_class": "strategic_sigint",
        "class_name": "fixed_wing",
        "min_airfield": "small_airport",
        "isr_type": "sigint_elint",
    },
    description="Strategic SIGINT/ELINT. +1 scan range + adversary-emitter catalog.",
))
_add(Sku(
    "groundtrack-jstars", "Groundtrack (E-8 JSTARS-analog)", "aircraft",
    price_usd=300_000_000, power_w=0, form_factor="aircraft",
    lead_time_s=_d(86_400 * 365),
    capabilities={
        "aircraft_class": "gmti",
        "class_name": "fixed_wing",
        "min_airfield": "small_airport",
        "isr_type": "gmti",
    },
    description="Ground moving target indicator. Tracks hostile motor movement.",
))

# --- Aircraft: high-altitude recon + stealth (military) --------------
# Operating over hostile airspace requires stealth_class >= low_observable.

_add(Sku(
    "spyglass-u2", "Spyglass-U2 (U-2 Dragon Lady-analog)", "aircraft",
    price_usd=180_000_000, power_w=0, form_factor="aircraft",
    lead_time_s=_d(86_400 * 365),
    capabilities={
        "aircraft_class": "high_altitude_recon",
        "class_name": "fixed_wing",
        "min_airfield": "small_airport",
        "stealth_class": "altitude",
        "service_ceiling_ft": 70_000,
    },
    description="70,000 ft recon. Altitude as defense; vulnerable to modern SAMs.",
))
_add(Sku(
    "blackbird-71", "Blackbird-71 (SR-71-analog, plot-gated)", "aircraft",
    price_usd=400_000_000, power_w=0, form_factor="aircraft",
    lead_time_s=_d(86_400 * 730),
    capabilities={
        "aircraft_class": "strategic_recon",
        "class_name": "fixed_wing",
        "min_airfield": "small_airport",
        "stealth_class": "speed_altitude",
        "service_ceiling_ft": 85_000,
        "gate_min_owned_isr": 2,
    },
    description="Mach 3+ strategic recon. Legacy airframe; Foundation-tier unlock.",
))
_add(Sku(
    "raptor-22", "Raptor-22 (F-22-analog)", "aircraft",
    price_usd=250_000_000, power_w=0, form_factor="aircraft",
    lead_time_s=_d(86_400 * 365),
    capabilities={
        "aircraft_class": "stealth_air_superiority",
        "class_name": "fixed_wing",
        "min_airfield": "small_airport",
        "stealth_class": "stealth",
        "armed": True,
    },
    description="5th-gen air-superiority stealth. Overflight under contested airspace.",
))
_add(Sku(
    "lightning-35", "Lightning-35 (F-35-analog)", "aircraft",
    price_usd=110_000_000, power_w=0, form_factor="aircraft",
    lead_time_s=_d(86_400 * 365),
    capabilities={
        "aircraft_class": "stealth_multirole",
        "class_name": "fixed_wing",
        "min_airfield": "small_airport",
        "stealth_class": "stealth",
        "armed": True,
    },
    description="5th-gen multirole stealth. Sensor-fusion ISR + strike.",
))
_add(Sku(
    "phantom-47", "Phantom-47 (F-47-analog, NGAD prototype)", "aircraft",
    price_usd=500_000_000, power_w=0, form_factor="aircraft",
    lead_time_s=_d(86_400 * 730),
    capabilities={
        "aircraft_class": "stealth_6gen",
        "class_name": "fixed_wing",
        "min_airfield": "private_airfield",
        "stealth_class": "ultra_stealth",
        "armed": True,
        "gate_min_owned_stealth": 2,
    },
    description="6th-gen NGAD-class prototype. Extreme stealth + sensor-fusion.",
))

# --- Port infrastructure ----------------------------------------------

_add(Sku(
    "small_port", "Small commercial port", "port",
    price_usd=2_000_000, power_w=5_000, form_factor="facility",
    lead_time_s=_d(86_400 * 30),
    capabilities={"port_tier": "small_port"},
    description="Single-berth commercial quay. Handles yachts, OSVs, research vessels.",
))
_add(Sku(
    "deepwater_port", "Deepwater port with cranes", "port",
    price_usd=25_000_000, power_w=40_000, form_factor="facility",
    lead_time_s=_d(86_400 * 180),
    capabilities={"port_tier": "deepwater_port"},
    description="Multi-berth deepwater facility. Handles tankers + icebreakers.",
))

# --- Surface ships ----------------------------------------------------

_add(Sku(
    "yacht-expedition", "Expedition yacht conversion", "ship",
    price_usd=15_000_000, power_w=0, form_factor="ship",
    lead_time_s=_d(86_400 * 120),
    capabilities={
        "ship_class": "small",
        "min_port": "small_port",
    },
    description="30m converted expedition yacht. 8-14 bunks, VSAT + Starstream.",
))
_add(Sku(
    "osv-class", "Offshore supply vessel", "ship",
    price_usd=30_000_000, power_w=0, form_factor="ship",
    lead_time_s=_d(86_400 * 180),
    capabilities={
        "ship_class": "medium",
        "min_port": "small_port",
    },
    description="OSV with heli deck. Best price/capability ratio; 30-60 bunks.",
))
_add(Sku(
    "research-vessel", "Research vessel (ex-NOAA hull)", "ship",
    price_usd=60_000_000, power_w=0, form_factor="ship",
    lead_time_s=_d(86_400 * 240),
    capabilities={
        "ship_class": "medium",
        "min_port": "small_port",
    },
    description="Full laboratory fitout + legitimate science cover identity.",
))
_add(Sku(
    "icebreaker-conv", "Converted ex-Soviet icebreaker", "ship",
    price_usd=150_000_000, power_w=0, form_factor="ship",
    lead_time_s=_d(86_400 * 365),
    capabilities={
        "ship_class": "heavy",
        "min_port": "deepwater_port",
    },
    description="Polar-capable hull. Extreme fuel burn, but goes anywhere.",
))

# --- Ground station infrastructure (per-site) -------------------------

_add(Sku(
    "portable_uplink", "Portable phased-array uplink", "ground_station",
    price_usd=120_000, power_w=200, form_factor="facility",
    lead_time_s=_d(86_400 * 7),
    capabilities={"ground_station_tier": "portable"},
    description="Kymeta-class flat-panel. Commands owned comms sats.",
))
_add(Sku(
    "fixed_small_dish", "Fixed 3m Ka/Ku station", "ground_station",
    price_usd=500_000, power_w=1_500, form_factor="facility",
    lead_time_s=_d(86_400 * 21),
    capabilities={"ground_station_tier": "fixed_small"},
    description="Permanent site-local uplink. Reliable but geo-bound.",
))

# --- Satellites (launch + on-orbit in one SKU for MVP) ----------------

_add(Sku(
    "cubesat-comms-3u", "QuantumCube 3U comms satellite (launched)", "satellite",
    price_usd=2_000_000, power_w=0, form_factor="space",
    lead_time_s=_d(86_400 * 60),
    capabilities={
        "satellite_class": "cubesat",
        "orbit": "LEO",
        "payload": "comms",
    },
    description="3U CubeSat comms — ~15W solar, Ku-band transponder, 2-3yr life.",
))
_add(Sku(
    "nimbus-comms", "Nimbus Small comms satellite (launched)", "satellite",
    price_usd=30_000_000, power_w=0, form_factor="space",
    lead_time_s=_d(86_400 * 180),
    capabilities={
        "satellite_class": "smallsat",
        "orbit": "LEO",
        "payload": "comms",
    },
    description="500 kg bus, Ka-band multi-beam regional. 10yr life.",
))
_add(Sku(
    "polaris-geo-comms", "Polaris GEO comms satellite (launched)", "satellite",
    price_usd=200_000_000, power_w=0, form_factor="space",
    lead_time_s=_d(86_400 * 365),
    capabilities={
        "satellite_class": "largesat",
        "orbit": "GEO",
        "payload": "comms",
    },
    description="3,500 kg GEO heritage bus — persistent wide-area coverage, 15yr life.",
))

# --- Payload-diverse satellites ---------------------------------------

_add(Sku(
    "cubesat-storage-3u", "QuantumCube 3U storage satellite", "satellite",
    price_usd=3_000_000, power_w=0, form_factor="space",
    lead_time_s=_d(86_400 * 60),
    capabilities={
        "satellite_class": "cubesat", "orbit": "LEO", "payload": "storage",
    },
    description="3U rad-hard SSD array. +archive reward while on orbit.",
))
_add(Sku(
    "nimbus-storage", "Nimbus storage satellite", "satellite",
    price_usd=40_000_000, power_w=0, form_factor="space",
    lead_time_s=_d(86_400 * 180),
    capabilities={
        "satellite_class": "smallsat", "orbit": "LEO", "payload": "storage",
    },
    description="500 TB rad-hard orbital archive. Foundation pays more for orbital storage.",
))
_add(Sku(
    "cubesat-compute-6u", "QuantumCube 6U compute satellite", "satellite",
    price_usd=5_000_000, power_w=0, form_factor="space",
    lead_time_s=_d(86_400 * 75),
    capabilities={
        "satellite_class": "cubesat", "orbit": "LEO", "payload": "compute",
    },
    description="6U edge NPU. Speeds Foundation analyses while on orbit.",
))
_add(Sku(
    "nimbus-compute", "Nimbus compute satellite", "satellite",
    price_usd=60_000_000, power_w=0, form_factor="space",
    lead_time_s=_d(86_400 * 200),
    capabilities={
        "satellite_class": "smallsat", "orbit": "LEO", "payload": "compute",
    },
    description="Rad-hard AI accelerator. Global analyze-speedup bonus.",
))
_add(Sku(
    "cubesat-sigint-3u", "QuantumCube 3U SIGINT satellite", "satellite",
    price_usd=4_000_000, power_w=0, form_factor="space",
    lead_time_s=_d(86_400 * 75),
    capabilities={
        "satellite_class": "cubesat", "orbit": "LEO", "payload": "sigint",
    },
    description="Wideband RF receiver. Scans find more candidate infohazards.",
))
_add(Sku(
    "nimbus-sigint", "Nimbus SIGINT satellite", "satellite",
    price_usd=50_000_000, power_w=0, form_factor="space",
    lead_time_s=_d(86_400 * 200),
    capabilities={
        "satellite_class": "smallsat", "orbit": "LEO", "payload": "sigint",
    },
    description="Direction-finding array. Stronger scan — more items + more Keter-class.",
))
_add(Sku(
    "nimbus-imint-eo", "Nimbus EO imager", "satellite",
    price_usd=80_000_000, power_w=0, form_factor="space",
    lead_time_s=_d(86_400 * 240),
    capabilities={
        "satellite_class": "smallsat", "orbit": "SSO", "payload": "imint",
    },
    description="0.5 m EO optical imager. Breach-site overwatch (future integration).",
))

# --- OTV-class reusable (plot-gated; requires prior GEO presence) -----

_add(Sku(
    "otv-class", "OTV-class reusable orbital vehicle", "satellite",
    price_usd=500_000_000, power_w=0, form_factor="space",
    lead_time_s=_d(86_400 * 730),
    capabilities={
        "satellite_class": "otv",
        "orbit": "LEO",
        "payload": "otv",
        "gate_min_geo_satellites": 1,
    },
    description=(
        "X-37-analog reusable vehicle. Payload bay + Earth-return. "
        "Requires established GEO presence to acquire."
    ),
))

# --- Submarine market -------------------------------------------------

_add(Sku(
    "barracuda-uuv", "Barracuda UUV (small autonomous)", "submarine",
    price_usd=1_000_000, power_w=0, form_factor="submarine",
    lead_time_s=_d(86_400 * 90),
    capabilities={"sub_class": "uuv", "min_port": "small_port"},
    description="<2 t autonomous UUV. Sensor + comms relay platform.",
))
_add(Sku(
    "kraken-xluuv", "Kraken XLUUV (autonomous medium)", "submarine",
    price_usd=60_000_000, power_w=0, form_factor="submarine",
    lead_time_s=_d(86_400 * 365),
    capabilities={"sub_class": "xluuv", "min_port": "small_port"},
    description="80 t autonomous XLUUV. 30-90 day endurance, 1-2 racks aboard.",
))
_add(Sku(
    "basalt-ssk-surplus", "Basalt-class SSK (surplus Kilo)", "submarine",
    price_usd=80_000_000, power_w=0, form_factor="submarine",
    lead_time_s=_d(86_400 * 540),
    capabilities={"sub_class": "ssk", "min_port": "deepwater_port"},
    description="Surplus Kilo-class diesel-electric. 45d endurance, 10-20 racks.",
))
_add(Sku(
    "typhoon-conversion", "Typhoon-class conversion", "submarine",
    price_usd=1_500_000_000, power_w=0, form_factor="submarine",
    lead_time_s=_d(86_400 * 1460),
    capabilities={
        "sub_class": "ssbn",
        "min_port": "deepwater_port",
        "gate_min_submarines": 2,
    },
    description=(
        "48,000 t ex-SSBN conversion. Full mobile DC + Ibex LPAR cluster. "
        "Requires prior fleet experience to acquire."
    ),
))

# --- More submarines: diesel-electric exports + surplus --------------

_add(Sku(
    "foxglove-surplus", "Foxglove-surplus (Foxtrot SSK)", "submarine",
    price_usd=10_000_000, power_w=0, form_factor="submarine",
    lead_time_s=_d(86_400 * 365),
    capabilities={"sub_class": "ssk", "min_port": "small_port"},
    description="Ex-Soviet Project 641 stripped hulk. Cheap entry; heavy refit.",
))
_add(Sku(
    "mako-type209", "Mako-class (Type 209-analog)", "submarine",
    price_usd=400_000_000, power_w=0, form_factor="submarine",
    lead_time_s=_d(86_400 * 1825),
    capabilities={"sub_class": "ssk", "min_port": "small_port"},
    description="German export diesel-electric SSK. 50 d endurance, 30 crew.",
))
_add(Sku(
    "stingray-aip-type214", "Stingray AIP (Type 214-analog)", "submarine",
    price_usd=700_000_000, power_w=0, form_factor="submarine",
    lead_time_s=_d(86_400 * 2190),
    capabilities={"sub_class": "ssk_aip", "min_port": "small_port"},
    description="AIP diesel-electric. 3 weeks fully submerged; high stealth.",
))
_add(Sku(
    "scorpion-class", "Scorpion-class SSK (Scorpene-analog)", "submarine",
    price_usd=550_000_000, power_w=0, form_factor="submarine",
    lead_time_s=_d(86_400 * 1825),
    capabilities={"sub_class": "ssk", "min_port": "small_port"},
    description="French-design export diesel-electric. 50 d endurance.",
))
_add(Sku(
    "shark-ssn-surplus", "Shark-class SSN (Victor-III surplus)", "submarine",
    price_usd=1_200_000_000, power_w=0, form_factor="submarine",
    lead_time_s=_d(86_400 * 1460),
    capabilities={
        "sub_class": "ssn",
        "min_port": "deepwater_port",
        "gate_min_submarines": 1,
    },
    description="Surplus nuclear attack sub. Months submerged, 40-80 racks.",
))


def list_by_category(category: str | None = None) -> list[Sku]:
    if category is None:
        return sorted(SKUS.values(), key=lambda s: (s.category, s.price_usd))
    return sorted(
        (s for s in SKUS.values() if s.category == category),
        key=lambda s: s.price_usd,
    )


def get(sku_id: str) -> Sku | None:
    return SKUS.get(sku_id)


def categories() -> list[str]:
    return sorted({s.category for s in SKUS.values()})
