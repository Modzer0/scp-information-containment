# SCP: Information Containment — Design

**Status:** Scope frozen — pending final open decisions listed in §27.
**Scope:** Single consolidated design for a terminal-based, real-time-clock information-containment operations simulator. Trademark-safe naming throughout; real-world analogs noted for reference only.

---

## 0. TL;DR

You operate a Foundation-adjacent information-security org. You crawl anomalous data sources, acquire suspected infohazards, analyze them inside appropriately rated containment (VMs, encrypted-memory mainframe LPARs, air-gapped tape), and archive the classified results for funding. The simulation runs in **real wall-clock time** (no acceleration, no pause) against a local daemon, so the org keeps running when you're closed — your employees execute standing orders on your behalf. Success requires designing a multi-site, multi-platform operation spanning land DCs, ships, submarines, aircraft, and exotic sites, coordinating staff training, logistics, power, comms, research, and risk. The game teaches through **mistakes**: mishandling an item in an under-rated VM produces a gradual, legible leak with a traceable root cause — and usually a 3 AM pager call.

---

## 1. Core pillars

1. **Real wall-clock time.** In-game time ≡ UTC, NTP-disciplined. No 2×, no pause. Durations are author-picked to feel authentic on a weeks-to-months player arc, not years.
2. **You operate, you don't play.** A background daemon ticks while the TUI is closed. Sessions are shift check-ins (~3–6/day, ~5–15 min each), punctuated by pager alerts.
3. **Procedure is the fantasy.** The horror is bureaucratic. Breaches trace to specific mistakes: the checklist you skipped, the playbook hole, the delegated authority you forgot to revoke.
4. **Skill-gated access, not skill-gated understanding.** New players get hard rails and suggested commands; veterans unlock expert mode. Nobody needs to already be an IT expert.
5. **Every system is legible.** Containment ratings are numeric sums, leak is a delta integrated over time, infection is deterministic given mistake + item profile. No hidden RNG punishment.
6. **Logistics as a first-class layer.** Ground, sea, air, and orbit transport are separate modeled layers with real capacity, speed, and visibility tradeoffs.
7. **Trademark-safe but concrete.** Renamed real-world hardware preserves authentic specs so players with the background recognize the references without legal risk.

---

## 2. Table of contents

1. Pillars (above)
2. TOC (this)
3. Core loop
4. Real-time model & daemon
5. Skill system
6. Infohazard items
7. Mistakes → infection
8. Containment rating vs. hazard strength
9. VMs, encryption, mainframes
10. Hardware catalog (compute)
11. Networking & connectivity
12. Power & cooling
13. Facilities (land)
14. Maritime fleet (surface + submarine + UUV)
15. Aerospace (crewed + UAV + HAPS)
16. Autonomous systems & redundancy
17. Staff (all lanes)
18. Training, clearances, pager, delegation
19. Research & development
20. Modular design language
21. Logistics, contracts, markets
22. Refit yards & acquisition projects
23. Economy & funding
24. Threats, GOIs, events
25. Technical architecture
26. Phased build plan
27. Open decisions (final call needed)
28. Out-of-scope / deferred

---

## 3. Core loop

One "shift" = one check-in. The underlying sim is continuous.

1. **Scan** noisy sources (deep web, field reports, radio intercepts, intercepted transmissions). Candidate infohazards surface with partial metadata.
2. **Acquire** promising candidates to quarantine storage (costs bandwidth, storage budget).
3. **Analyze** inside a containment environment appropriate for the item's class (costs CPU, RAM, operator attention, carries exposure risk).
4. **Classify** and route: archive to tape, cold-store, neutralize, or delete (misclassification → mistake, see §7).
5. **Invoice O5** → funding → upgrade rig, hire, train, research, or deploy.
6. **Respond** to incidents, breaches, GOI actions, and supply events in between.

---

## 4. Real-time model & daemon

### 4.1 Clock

- Simulation clock ≡ system clock, NTP-disciplined UTC.
- Monotonic progress: tick count never goes backwards even if system clock does.
- All scheduled events are stored as UTC timestamps, not tick offsets.

### 4.2 Daemon

- Long-running local service (systemd / launchd / Windows Service).
- Owns the event queue, tick loop, and SQLite journal.
- TUI is a thin client that attaches to the daemon via local socket.
- On daemon start, replays missed time against the event queue.

### 4.3 Durations (canonical)

Action durations are authored, not tick-abstract. Rough table:

| Action | Wall-clock |
|---|---|
| Scan source | 30 s – 5 min |
| Analyze Safe-class | 2 – 20 min |
| Analyze Keter-class (encrypted VM) | 1 – 6 h |
| Forensic wipe + reprovision (one box) | 20 – 60 min |
| Tape archive spool | 10 – 45 min |
| Train analyst (entry) | 4 – 8 h |
| Train Memeticist (Level-3) | 3 – 5 days |
| Field-cert an agent | 2 – 3 days |
| Train licensed reactor op | 4 – 8 weeks |
| Transport MobiDC (truck, cross-country) | 6 – 18 h |
| Subsea pod deployment | 5 – 10 days |
| Stand up on-prem rack | 1 – 2 days |
| Mainframe procurement + install | 1 – 2 weeks |
| Diesel delivery SLA | 4 – 24 h |
| Dry-dock (SSK) | 2 – 4 weeks |
| Dry-dock (SSN / Typhoon) | 4 – 12 weeks |
| Research project (incremental) | 2 – 6 weeks |
| Research project (new module unlock) | 2 – 6 months |
| Research project (breakthrough) | 6 – 18 months |
| Fiber build-out (regional) | 3 – 12 weeks |

Heuristic: real-world timelines compressed **~10–30×** except interactive actions which stay near-real.

### 4.3.1 Runtime time compression

Two knobs for time scale:

- **`SCP_TIME_SCALE`** env var (daemon-wide, author-level): baked into
  every duration at import. The canonical design-target compression
  (~10–30×) can be set here. Shipped default is `1.0` so durations
  match the §4.3 table verbatim.
- **Runtime multiplier** (per-save, player-level): stored in the
  settings table, changeable at any time via the `speed` command.
  Default `1.0`. Presets: `pause` (0.0001×), `realtime` (1×),
  `fast` (5×), `faster` (25×), `turbo` (100×), `ludicrous` (1000×),
  `plaid` (10000×). Any positive number in `[0.0001, 10_000]` is
  accepted. `speed` with no argument shows the current setting.

The scheduler divides its sleep between events by the multiplier, so
a nominal 1-hour ETA fires after 36 real-seconds at 100×. Stored ETAs
remain absolute wall-clock UTCs — the compression is applied at wait
time, not at schedule time. A speed change mid-sleep takes effect on
the next re-check (≤60s real, typically instant because the IPC
handler wakes the scheduler).

The multiplier is shown in `sitrep` and persists across daemon
restarts. It's designed for players who don't want to wait days of
wall-clock for a mainframe procurement — set `speed ludicrous` and
the 14-day install completes in ~20 minutes real time.

### 4.4 Offline tolerance

When host is powered off, the sim **pauses** (see Open Decisions, §27). On next daemon start, catch-up replay runs the event queue forward to now. Staff on standing orders make decisions via their autonomy rules (see §18). Any event requiring escalation is held in the pager inbox for the player's next check-in.

---

## 5. Skill system

### 5.1 Skills (player-avatar and employees share the same scale)

`infosec` · `sysadmin` · `networking` · `ml_ops` · `memetics` · `forensics` · `field_ops` · `logistics` · `electrical` · `research_methodology` · `materials_science` · `cryptography` · `power_systems` · `bioscience` · `comms_engineering` · `control_theory` · `naval_architecture` · `fixed_wing_pilot` · `rotary_pilot` · `uav_operator` · `ifr_rated` · `multi_engine` · `a&p_mechanic` · `avionics` · `airborne_sigint` · `mariner_deck` · `mariner_engineer` · `reactor_operator`

Range 0–100. XP from use; levels gate work tiers.

### 5.2 Guardrail ramp

TUI protection scales inverse to skill:

| Skill | Behavior |
|---|---|
| 0–20 | Hard rails — unsafe actions refused with pointer to correct workflow |
| 20–50 | Soft rails — confirm dialog, must type `OVERRIDE` |
| 50–80 | Silent warnings in log pane |
| 80+ | Expert mode — no rails |

Veterans can move fast; they're also the ones who make the *interesting* mistakes.

### 5.3 Currency (use-it-or-lose-it)

Pilots, reactor operators, field agents, and select technical staff require recurring proficiency:
- Pilots: X hours per X days to maintain revenue-flight currency
- Reactor ops: recurring simulator cycles
- Field agents: annual recertification

Gone-cold staff can be re-currencied, but it's a cost and a schedule hit.

---

## 6. Infohazard items

### 6.1 Model

Each item is a procedural record:

```
item = {
  id, designation, class,        # Safe | Euclid | Keter | Thaumiel | Apollyon (rare)
  hazard_strength,                # numeric
  memetic_load,                   # 0–10
  cognitohazard_class,            # 0–10
  self_propagation,               # 0–10
  encryption,                     # handling-required
  payload_profile,                # vector tags
  required_containment,           # numeric threshold
  source_metadata,                # where acquired, intake vector
}
```

### 6.2 Procedural generation

Template-driven: designation/class/signature/risk/payload composition. Procedural for open-ended runs; optional hand-authored campaign items seeded into the stream.

### 6.3 Partial reveal

On scan, only noisy metadata is visible. Full profile surfaces progressively through acquisition, pre-analysis profiling, and analysis itself. Players trade throughput (quick analyze) for safety (profile first).

### 6.4 Classes & thresholds

| Class | Required containment min | Typical hazard strength |
|---|---|---|
| Safe | 3 | 1–5 |
| Euclid | 8 | 5–12 |
| Keter | 16 | 12–22 |
| Thaumiel | 12 | mixed, weaponizable |
| Apollyon | 24+ | story-gated, rare |

---

## 7. Mistakes → infection

### 7.1 Principle

Infection is **deterministic given the player/staff action**. The hidden variable is the item profile. Correct handling for the profile is safe. Incorrect handling creates an *exposure event* that the engine propagates from. No bad-luck rolls (open decision §27).

### 7.2 Mistake taxonomy (each is a named event)

**Isolation:** opening on a workstation; clipboard across VM→host; shared-folder mount quarantine↔prod; USB from field into clean desk; tape reader on networked host.

**VM hygiene:** reused VM without snapshot rollback; tainted golden image; encryption disabled "to go faster"; Keter assigned to non-LPAR VM.

**Process:** skipped pre-analysis checklist; stale mnestic signature DB; misclassified class; ignored kant-counter spike.

**Delegation:** Level-2 analyst autonomously handling Euclid+; playbook hole; uncertified field agents; no on-call coverage in a time zone.

**Infrastructure:** bandwidth-starved analysis; brownout; neglected sub maintenance → cable corruption; fuel contract lapse.

**Forensic:** wipe before air-gap; restore from unverified golden image; no media destruction for self-propagating items; un-mnesticed field debrief.

### 7.3 Exposure model

```
exposure = {
  item_id, host_id, vector, timestamp,
  mem_residency:  bool,
  disk_residency: bool,
  network_reach:  set[host_id],
  memetic_reach:  set[person_id],
}
spread_per_tick = f(item.self_propagation, item.memetic_load,
                    segmentation_quality, scanner_freshness, staff_skill)
```

Segmentation is real. Flat networks fail fast. Air gaps are binary. Mnestic-aware staff resist memetic reach.

### 7.4 Infection states (per host)

`clean → suspect → glitchy → infected → propagating`

Progression is time-based given exposure; regression requires intervention (detection → clean → wipe → reimage; worst case physical destruction).

### 7.5 Incident report

Auto-generated at detection. Example:

```
INCIDENT #0042 · SEV: ALERT · 2026-04-21 03:14:07 UTC

ITEM        SCP-████ (class: Keter, memetic, self-propagating)
HOST        vm-03 on dgz-pod-01 (unencrypted memory)
VECTOR      analyze command issued without --isolation=encrypted

ROOT CAUSE  item class required encrypted-memory VM (Ibex LPAR);
            issued analysis to standard VM pool instead.

CONTRIBUTING
  • dgz-pod-01 hosts vm-03..07 on shared memory substrate
  • heuristic scanner DB 6 days stale (update contract suspended)
  • on-call analyst Dr. Vey (skill 42) lacked Keter handling cert

EXPOSURE    4 VMs, 1 operator (Dr. Vey), spread p=0.71/tick
RECOMMEND   air-gap dgz-pod-01; forensic wipe vm-03..07;
            Dr. Vey → mnestic protocol + stand-down

SKILL XP    +12 memetics (Vey), +6 forensics (you)
```

Incident inbox is permanently browsable. This is the game's pedagogy.

---

## 8. Containment rating vs. hazard strength (graceful failure)

### 8.1 Rating components

```
containment =
    memory_encryption     (0 none | 3 software | 6 hardware-SEV | 10 mainframe-LPAR)
  + isolation             (0 shared-kernel | 2 hypervisor | 5 bare-metal | 8 air-gapped)
  + mnestic_firmware      (0 | 2 | 4 hardened)
  + physical_shielding    (0 | 2 Faraday | 4 polarized optics | 6 SCSC-hardened room)
  + scanner_freshness     (0 stale | 1 current | 2 signature-feed live)
```

### 8.2 Delta → behavior

```
delta = hazard - containment
delta ≤ 0     stable
delta 1–3     slow leak — metadata trickle, adjacent corruption, kant-jitter
delta 4–7     active leak — spread over shared substrate, operator exposure rising
delta 8+      catastrophic — payload live, network stack imminent
```

Time-integrated. A Safe-rated VM can hold a Euclid item briefly (~20 minutes) before meaningful leak; it holds Keter for seconds. Undersized containment fails **gradually and noisily** before it fails catastrophically — warning signs precede collapse.

---

## 9. VMs, encryption, mainframes

### 9.1 VM tiers

- **Standard VM** (hypervisor, shared kernel, software encryption): Safe, Euclid-with-care
- **Isolated VM** (bare-metal, hardware mem encryption): Euclid comfortably
- **Mainframe LPAR** (Ibex Z-class, encrypted memory per LPAR, physical isolation): Keter
- **Airgapped analysis station** (no network, manual media in/out): high-risk novel items

### 9.2 Critical property

Encrypted-memory VMs on mainframes are the **only reliable containment for self-propagating memetic payloads**: even if a VM is compromised, the hazard cannot read adjacent VMs' memory.

### 9.3 VM hygiene (rules the engine enforces)

- Fresh snapshot rollback between items (unless research unlocks bulk-item protocols)
- Scanner signature DB currency check at analysis start
- Operator cert check against item class
- Pre-analysis checklist completion required for Euclid+

### 9.4 Multi-VM hosts & memory budget

A host can run multiple VMs. Each VM gets an equal share of the host's
RAM: `allocated_ram_gb = host_ram_gb // vm_count`. Adding a VM *shrinks*
every sibling's budget. Removing one doesn't magically resize in-flight
analyses — you can't provision a new VM while any sibling is busy.

**Per-class VM ceiling:**

| Host class | Cap | Rationale |
|---|---|---|
| server    | 32 | Standard hypervisor density |
| aipod     | 16 | Wants more RAM per VM for large-model analyses |
| mainframe | 64 | LPAR-style ceiling; each LPAR is still beefy |

Additionally a per-VM RAM floor of 8 GB applies. A 64 GB host tops out at
8 VMs regardless of class; a 256 GB server at 32 (class cap, not the
RAM-floor cap of 32).

**Analyze RAM gate:** an item's `size_gb` must fit in the chosen VM's
`allocated_ram_gb` — no swap, no streaming. A 500 GB Keter requires
either a 512 GB+ VM (single-VM on a 512 GB host, or single-VM on half of
a 1 TB host, etc.) or must be declined. This is the mechanical reason
the high-end compute catalog exists and why mainframes aren't just
"fancier servers": they're where Keter analysis happens.

Strategic shape this creates:
- Early game: one modest VM on the bootstrap 64 GB host; Safe only.
- Mid game: multiple VMs on a mid-tier server for bulk Safe/Euclid.
- Late game: dedicate a large host to a single VM when a juicy Keter
  item lands, accept the throughput hit for the capability.

### 9.5 Host-inherited base containment

When a VM is provisioned on a host, it inherits the host's baseline
containment spec. The mainframe (`ibex-z-base`) ships with
`auto_vm_spec = {memory_encryption: 10, isolation: 8, mnestic_firmware: 4,
physical_shielding: 6, scanner_freshness: 2}` — every LPAR starts at
containment 30, not the generic seed. Servers and AI pods without that
capability fall back to the seed spec (containment ~6). This is why
mainframes justify their price tag beyond raw RAM: every LPAR carried
by the hardware is Keter-ready out of the box.

The `auto_vm_spec` is stored on the host row at install time, so any
additional VM provisioned later inherits the same baseline (not just
the first one procurement creates).

### 9.6 VM deprovisioning

VMs can be torn down with `deprovision_vm <vm_id>`. Requirements:

- VM must not be `busy` (in-flight analyses can't have their RAM yanked).
- Any `current_vm_id` pointer on items referencing this VM is cleared.
- Freed RAM share is redistributed across remaining VMs on the host.
- Dropping to zero VMs on a host is allowed — the host remains, and
  provision_vm can stand one back up.

### 9.7 Compound compute modules

Some catalog items aren't single hosts — they're shipping containers or
subsea capsules that unpack into multiple hosts plus cooling equipment.
The `compute_module` category describes this via a `bundle` list:

```
panthalassa-core (compute_module):
  bundle:
    - kind: host   count: 4  host_class: server
      specs: {ram_gb: 512, storage_gb: 12_000, ...}
      auto_vm_spec: {physical_shielding: 4, ...}   # cont 10 per VM
    - kind: cooling  count: 2  ctype: seawater_loop  kw: 60
  site_cooling_kw_bonus: 120
```

Installation fans out: one purchase creates N host rows (each with its
own seeded VM carrying the bundle's `auto_vm_spec`), M cooling unit
rows, and optionally bumps the site's cooling capacity via
`site_cooling_kw_bonus`. Pricing is carried by the compound SKU — the
bundle children don't bill separately.

Current compound modules:

| SKU | Hosts | Cooling | Per-VM Cont | Notes |
|---|---|---|---|---|
| `container-compute-20ft` | 4 × 512 GB | 2 × RDHX 40kW | seed ~6 | Generic field DC |
| `container-compute-20ft-hs` | 4 × 512 GB | 2 × RDHX 40kW | **21** | Hardened: Faraday + SCSC + mnestic + SEV + bare-metal |
| `panthalassa-core` | 4 × 512 GB | 2 × seawater loop | 10 | Subsea-hardened housing |
| `panthalassa-array` | 8 × 1 TB | 4 × seawater loop | 10 | Full-rack subsea |

### 9.8 Host-wide containment modules

Previously, upgrading a host full of VMs to Faraday-grade shielding meant
buying one `vm_module` per VM. New category `host_containment_module`
solves this: one purchase targets a HOST and applies to:

1. The host's stored `auto_vm_spec` (so newly provisioned VMs inherit),
2. Every VM currently on the host (taking `max(existing, new)` so it
   never downgrades).

Catalog (all take-max cascades):

| SKU | Component | Value |
|---|---|---|
| `host-faraday-cage` | physical_shielding | 2 |
| `host-polarized-shielding` | physical_shielding | 4 |
| `host-scsc-vault` | physical_shielding | 6 |
| `host-mnestic-firmware` | mnestic_firmware | 4 |
| `host-hw-memenc` | memory_encryption | 6 |
| `host-bare-metal-isolation` | isolation | 5 |

Stacking different components (mnestic + memenc + SCSC) on the same host
yields a rack-wide Keter-grade baseline without touching each VM
individually. Crucially, subsequent `provision_vm` calls on that host
also inherit the upgraded baseline — one investment, ongoing return.

---

## 10. Hardware catalog (compute)

All names are trademark-safe renames; real-world analogs shown for the author's reference.

### 10.1 Clients & endpoints

| Class | In-game | Real analog | Role |
|---|---|---|---|
| Laptop | ThinkBook T-series, **Pear MacBud Pro M5** | ThinkPad T-series, MBP | Field analyst kit |
| Desktop | Generic tower | Dell OptiPlex | Office work |
| Workstation | **Pear MacBud Studio M5 Ultra** | Mac Studio | Local ML prototyping |
| ARM field node | **Rasberry Pi Compute**, **Pear Mini M5** | Raspberry Pi, Mac mini | Solar-powerable field |

### 10.2 GPUs (consumer / prosumer)

- **GForce QTX 5090** (Invidia) — flagship gaming/ML
- **Radian RX 9900** (ADM)
- **Archon B-series** (Intrel)
- Workstation: **Invidia Quadrille**, **ADM Radian Pro W**

### 10.3 AI accelerators & NPUs

- **Invidia I200 / I300 Blackhall** — flagship training; eye-watering power
- **Invidia DGZ pods** (8×I300) — containerized training nodes
- **Alphabyte Tensor v7** (Googol) — inference-per-watt leader; cloud-rent default
- **Tenstorrent Wormhole / Blackhole** — open-arch; best perf/$ with ml_ops skill tax
- **Cerebrium WSE-class** — wafer-scale; rare event unlock

### 10.4 Mainframes

- **Ibex Z-class** — IBM z16 analog; $3–5M base + licensing; encrypted-memory LPARs (endgame containment)
- **Unisys-equivalent legacy** — bargain used-market plays

### 10.5 Power / heat envelope (representative)

Each SKU in the catalog carries: price, TDP (W), idle watts, heat output (BTU/hr derived), rack U, weight, interface. Real values drive the power/cooling sim.

---

## 11. Networking & connectivity

### 11.1 Per-site link profile

Every site has: `{bandwidth, latency_p50, latency_p99, jitter, uptime_sla, stealth_class}`.

### 11.2 Tiers

| Tier | Speed | Latency | Where | Cost |
|---|---|---|---|---|
| Dial-up / 4G fallback | 1–20 Mbps | 60–200 ms | anywhere, last-resort | cheap |
| DSL / cable | 50–500 Mbps | 20–50 ms | urban + most rural | low |
| Business fiber | 1–10 Gbps | 2–10 ms | cities, commercial zones | mid |
| Dark fiber / metro-E | 10–100 Gbps | 1–5 ms | major-metro DCs | high |
| Player-laid fiber | 1–40 Gbps | route-dependent | anywhere you pay | huge capex, weeks |
| Microwave PtP | 100 Mbps – 1 Gbps | 1–3 ms | LOS, remote | mid + engineering |
| LEO sat (**Starstream**) | 50–300 Mbps | 25–60 ms | global inc. maritime | subscription |
| MEO sat | 30–100 Mbps | 80–150 ms | polar, maritime | high |
| GEO sat | 5–30 Mbps | 500–650 ms | last-resort | cheap-ish |

### 11.3 Gating examples

- Real-time memetic containment requires `latency_p99 < 50 ms`. GEO sat disallowed.
- Cloud TPU rental needs `≥ 1 Gbps && < 30 ms` or training starves.
- Fiber build-out is a multi-phase project (survey → permits → trench → splice → light), each phase timed with fail-stops.

### 11.4 Subsea / submerged comms

See §14 for sub-specific ELF / acoustic / buoy uplinks.

---

## 12. Power & cooling

### 12.1 Power supply tiers

| Source | Use | Notes |
|---|---|---|
| Grid | Urban/colo sites | $/kWh per region; outage risk |
| Diesel genset | Any site, backup or primary | Needs fuel contract + SLA |
| Propane genset | Remote sites | Cleaner, more fuel-dense than diesel by weight |
| Solar + battery | ARM field nodes < 300 W sustained | Weather-dependent |
| Wind + battery | Remote, windy sites | Seasonal variability |
| Micro-reactor (1–10 kW) | Micro field base | $8–15M, 2 licensed ops, 10-yr fuel |
| Mobile SMR (1–5 MW) | Remote/Antarctica/MobiDC cluster | $50–150M, 4–8 ops, weeks to deploy |
| Deployable SMR (20–50 MW) | Capital site | $300M–$1B, 12+ ops, months on-site |
| OTEC | Panthalassa-class subsea | Research-unlock |

### 12.2 Cooling tiers

| Type | PUE (approx) | Notes |
|---|---|---|
| Air (room AC) | 1.5 | Low capex, density-limited |
| Rear-door heat exchanger | 1.2 | Medium capex |
| Direct-to-chip liquid | 1.1 | Higher capex, high density |
| Immersion | 1.05 | High capex, highest density |
| Seawater | 1.02–1.05 | Subsea / hull, free working fluid |
| Passive (Antarctic) | 1.02 | Winter; still needs circulation |
| Ground-loop | 1.1 | Underground, moderate loads only |

### 12.3 Fuel contracts

Diesel / propane / Jet-A / MGO contracts have:
- Delivery SLA
- Price-lock duration
- Minimum take
- Sanction/political risk per supplier

Lapse = brownout → corrupted in-flight analyses → mistake cascade.

### 12.4 Reactor accidents, refueling, spent-fuel storage (future phase)

Reactors are serious infrastructure. This section formalizes the accident,
maintenance, and waste-handling layers — **not yet implemented**; the
current catalog has reactor SKUs with `passive_safety` metadata ready to
drive these mechanics.

#### Accident taxonomy

| Event | PWR / SMR | MSR | Gameplay signal |
|---|---|---|---|
| Loss-of-coolant (LOCA) | Possible; pressurized steam blowdown; requires ECCS | Not applicable — atmospheric primary, freeze-plug drain | PWR: BREACH; MSR: NOTICE (clean drain) |
| Fuel damage / cladding breach | Plausible at high burnup | Fuel is already liquid; cleanup = salt decon | PWR: ALERT with contamination radius; MSR: NOTICE |
| Primary loop rupture | Catastrophic — site evacuation | No high-pressure loop; contained drain | PWR: BREACH; MSR: NOTICE |
| External event (seismic, flood) | Depends on site hardening | Same hardening; salt solidifies if power lost | Both: severity scaled by hardening |
| Operator error (control-rod mis-trip) | Can scram; recoverable if caught fast | MSR drains and waits for restart | PWR: ALERT; MSR: NOTICE |
| ASAT / kinetic attack on site | Catastrophic regardless of reactor type | — | BREACH; see threat model §24 |

**Annual per-reactor base rate (target design target):**
- PWR microreactor: ~0.5% / year of some incident class
- Mobile SMR (PWR): ~0.3% / year
- Deployable SMR (PWR): ~0.2% / year
- MSR (μ or SMR): ~0.15% / year — and when one occurs, severity is usually one tier lower than PWR equivalent

Rolls happen on a `reactor_incident_roll` scheduler event (analogous to
existing `outage_roll`). Severity determines journal severity + site
response requirements.

#### Cleanup procedure

On an active-severity incident (ALERT or BREACH):

1. **Immediate** — site reports `reactor_incident_active`; affected
   power_plant goes `status='offline'`. Effective power capacity drops.
2. **Exclusion zone** — staff at the affected site are placed on
   stand-down (new status `quarantined_reactor` or similar) for the
   duration of hot-zone work. Cannot act as operators.
3. **Response crew** — requires `reactor_operator` + `forensics` staff
   assigned. Cleanup duration scales with severity tier:
   - NOTICE: 1–3 days (MSR typical)
   - ALERT: 1–4 weeks (PWR fuel cladding damage)
   - BREACH: 3–12 months (primary rupture; may end the site)
4. **Return to service** — if recoverable, reactor status flips to
   `refueling` or `cold_shutdown` depending on damage. Full restart
   requires operator re-certification on the specific unit.
5. **Irrecoverable** — reactor marked `decommissioned`; spent fuel
   proceeds to storage (below). Site capacity is permanently reduced
   unless another plant is installed.

#### Refueling operations

Each reactor has a fuel cycle; refueling is scheduled maintenance that
takes the reactor offline for a fixed duration:

| Reactor | Cycle | Outage duration | Fuel cost |
|---|---|---|---|
| `kilopower-micro` | 10 yr | 2 weeks | $500k |
| `evinci-mobile-smr` | 3–7 yr | 3 weeks | $5M |
| `nuscale-smr` | 18–24 months | 30–40 days | $15M |
| `msr-micro` | continuous salt cleanup + yearly top-up | 3–5 days | $2M/yr |
| `msr-smr` | continuous + 6-month salt service | 1 week | $8M/yr |

Scheduled `refueling_due` event; player schedules a `refueling_start`
during a low-load window. If refueling is overdue, reactor derates
then shuts down.

Refueling **requires licensed reactor operators** on staff (new hard
gate — current catalog already declares `requires_licensed_ops` per
reactor SKU). Existing `reactor_operator` recruitment role (currently
implemented for hiring) feeds into this.

#### Spent-fuel storage

Waste products accumulate. Real-world stages:

1. **Spent fuel pool** — 5+ years of active cooling; wet storage on-site
2. **Dry cask storage** — multi-decade interim storage; passively cooled
3. **Geological repository** — final disposal (decades out, expensive)

In-game minimum viable:

- New `spent_fuel` entity table: `{id, reactor_id, removed_at, stage,
  site_id}` tracking individual assemblies
- New site_module SKU category `waste_storage`:
  - `pool-wet-storage` — short-term; cheap; small capacity
  - `dry-cask-vault` — long-term interim; medium capacity
  - `geological-repository` — plot-gated; unlimited; multi-year
    acquisition project (akin to yard relationships, §22)
- Each reactor refueling produces N spent-fuel assemblies that must
  land in a storage unit at the site or transit to another site with
  capacity (like item transit)
- Overflow: spent fuel in the refueling floor triggers `NRC-style`
  regulatory event (political cost)

#### Gameplay shape

A mature operation running reactors plans like a real nuclear fleet:
- Cycle stagger across multiple reactors so only one is down at a time
- Redundant pumps + backup gensets prevent station-blackout scenarios
  from becoming fuel-damage events
- MSR-tier sites handle Keter-scale work with lower accident exposure
- Spent-fuel logistics becomes a multi-decade background project

This design is ready to land whenever the operator wants; schema
needs a `spent_fuel` table, a `waste_storage` SKU category, and
`reactor_incident_roll` / `refueling_*` scheduled event kinds.

---

## 13. Facilities (land)

### 13.1 Tiers

| Form factor | Capex | Opex | Heat ceiling | Notes |
|---|---|---|---|---|
| Rack in office closet | $5–30k | low | small | Stealthy, severe density limit |
| Colocation | $0 capex | $/U/mo | N/A | No control, good latency |
| On-prem DC | $5–40M | high | high | Full control, power/cooling eng |
| **MobiDC container** (20/40 ft) | $2–10M | medium | high w/ immersion | Shippable; needs genset + chiller |
| **Subsea pod** (Panthalassa-class) | $40–120M + cable | medium | very high (seawater) | ~180–600 ms sat uplink, sea maintenance |
| **Underground base** | $50M–$1B+ | high (pumps, vent) | limited (heat rejection hard) | Excellent EM/memetic shielding |
| **Antarctica base** | extreme | 5–10× mainland | excellent (free passive cool) | Supply windows, treaty cover |

### 13.2 Underground specifics

- Excavation: real weeks-to-months
- Dewatering pumps: mandatory; fail → flood in hours for deep bases
- Ventilation: CO₂/radon scrubbers, positive pressure
- Heat rejection: hardest engineering problem; density cap unless piped to aquifer/lake
- Blast-hardening tier optional, large capex

### 13.3 Antarctica specifics

- Surface resupply Oct–Feb only; flights year-round (expensive, weather-limited)
- Power: nuclear is the rational tier
- Supply multipliers: ~5× consumables, ~10× equipment
- Cover: operate as a research flag; periodic inspection events
- Staff: 6-month tours; recruitment premium

### 13.4 Site security rating

Every site has a numeric `security_rating` computed per-roll as:

    rating = base[site_type] + Σ equipment_bonuses + Σ guard_contract_bonuses

**Base by site type** (tent = 5, field = 8, office_closet = 10, mobidc = 15,
onprem_dc = 25, oil_platform = 30, bunker_shallow = 45, antarctica = 50,
underground = 70, subsea_pod = 80). Cheaper hulls are more exposed by
default — a tent is a sitting duck until you bolt gear to it; a subsea
pod is effectively unreachable.

**Equipment catalog** (capex, per-site install):
- *physical:* perimeter fence, hardened safe room, blast doors
- *access:* RFID + biometric mantrap
- *detection:* CCTV + NVR, motion sensors, counter-UAS, honeypot network
- *shielding:* Faraday/TEMPEST
- *signals:* COMINT mast, ELINT array, IMINT dome (counterintel today;
  these same SKUs feed rival-site detection in §24.6)

Some SKUs are blocked on site types that can't physically host them
(no perimeter fence on a subsea pod; no blast doors on a tent).

**Guard contracts** (monthly billing via the contracts layer):
- `guard_watch_single` +3 ($6k/mo)
- `guard_watch_shift` +8 ($20k/mo)
- `pmsc_team_light` +15 ($50k/mo)
- `pmsc_team_heavy` +25 ($120k/mo)
- `mtf_squad` +40 ($250k/mo)

Guards lapse when contracts fail to bill — their bonus disappears from
the rating the instant the contract moves to `lapsed`.

**Incident rolls** fire once per game-day per site. Chance per site is
`max(0, (50 - rating) / 100)` — linear 50% at rating 0 down to 0% at
rating 50. When a roll fires, weighted pick:

- `attempted_breach` 50% — logged NOTICE, no damage
- `sabotage_power` 20% — 2h outage row created
- `sabotage_host` 20% — random clean host → `suspect`
- `theft` 10% — random archived SCP at site → `stolen` state; can no
  longer be transferred, analyzed, or read. Recovery is a future phase.

If an incident can't apply (no clean host, no archived item), it
degrades to `attempted_breach` rather than failing silently.

---

## 14. Maritime fleet

### 14.0 Vessel equipment + orders

Ships and submarines are not passive cargo haulers — each hull carries
modular equipment and can be dispatched on revenue-generating orders
that also produce intel and presence.

**Equipment categories** (installed via `install_equipment`):

- **Sensor** — towed/active sonar, maritime radar, ESM/ELINT suite,
  anomalous-acoustic hydrophone. Each contributes a numeric rating that
  boosts patrol/shadow payouts and (future) detection rolls. Ships-only
  for radar; subs-only for certain fits.
- **Stealth** — anechoic coating (subs only). Reduces detection chance
  in fog-of-war (consumed by planned §24.5 combat layer).
- **Comm** — encrypted satcom relay, VLF reception mast. Enables relay
  between friendly assets; VLF lets subs receive at depth.
- **Containment** — modular archive pods (50 TB / 500 TB). Enable the
  `standby_archive` order. 500 TB fits only heavy hulls (heavy surface,
  SSN/SSBN).
- **Science** — oceanographic suite. Cover-identity loadout.

Equipment can only be installed or removed while the vessel is berthed.
Each SKU has a `fits_vessel_types` and optional `fits_classes` gate.

**Orders** (issued via `order <ship|sub> <id> <kind>`):

- `patrol [hours]` — ISR sweep. Requires ≥1 sensor. Payout =
  `$5k/h × hull_mult × (1 + sensor_rating/10)`. Future: yields intel
  tokens that feed the rival-GOI fog-of-war.
- `escort_convoy [hours]` — protect trade lanes. Flat $40k × hull_mult.
  Future: reduces `transfer_item` loss-in-transit risk on the same route.
- `standby_archive [hours]` — act as a floating secure-archive-on-station.
  Requires ≥1 containment pod. Payout = `$1k/h × (pod_capacity_tb / 10)`,
  reflecting an O5 commission for offshore tape custody.
- `return_to_port <site> [hours]` — transit the vessel to a new base
  site. No payout; pure logistics move.

While on order, vessel status flips to `at_sea` (surface) or `submerged`
(sub). Completion fires a scheduler event that credits the payout,
berths the vessel, and applies any effect (e.g., new site for
`return_to_port`).

Hull-class multipliers drive the economy: medium surface = 1.5×,
heavy = 2.5×, UUV = 0.3×, SSN = 3×, SSBN = 5×. This is the lever for
tuning vessel capex vs expected lifetime payout.

### 14.1 Surface vessels

| Class | Real analog | Price | Bunks | Satcom | Notes |
|---|---|---|---|---|---|
| Yacht conversion | 30m expedition yacht | $8–20M | 8–14 | VSAT + Starstream | Small rig, weather-limited |
| Offshore supply vessel | OSV | $15–40M | 30–60 | Full suite | Best value, heli deck |
| Research vessel | ex-NOAA hull | $40–80M | 60–100 | Full + lab mod | Ideal cover |
| Icebreaker | ex-Soviet | $80–200M | 80–150 | Full | Polar ops, fuel burn brutal |
| Converted tanker (VLCC) | VLCC conversion | $100M+ | 200+ | Anything | Full MobiDC hotel |

Ops costs: licensed mariner crew (separate labor pool), bunker/MGO fuel, port fees, insurance, dry-dock cycle (~5 in-game years, 1-week offline).

### 14.2 Submarine catalog — full market

Trademark-safe renames; Typhoon preserved (NATO designation). Organized by market tier.

#### T1 — Retail / off-the-shelf

| Class | Real analog | Depth | Seats | Cost | Role |
|---|---|---|---|---|---|
| SeaForge NEMO | U-Boat Worx NEMO 2 | 100m | 2 | $1.2M | Sensor mule |
| SeaForge Cruiser-X | U-Boat Worx C-Explorer 5 | 300m | 5 | $5–8M | Small rack |
| Deepline Voyager | Triton 3300/3 | 1000m | 3 | $4–6M | Sensor + edge NPU |
| Deepline 7500/3 | Triton 7500/3 | 2300m | 3 | $18M | Edge NPU, mule |
| Surfskimmer | Seabreacher X | surface-30m | 2 | $95–120k | Comms relay |
| Argonaut AUV | Gavia / REMUS 100 | 500m | 0 | $150–400k | Sensor, relay |
| Argonaut-XL | Kongsberg HUGIN | 6000m | 0 | $3–7M | Edge inference |

#### T2 — Commercial / research

| Class | Real analog | Depth | Cost | Role |
|---|---|---|---|---|
| Argo-class HOV | Alvin, Shinkai 6500 | 6500m | $40–70M | Mobile Keter analysis w/ science cover |
| Abyssal-class HOV | DSV Limiting Factor | 11000m | $50M build | Unique deep-trench |
| WorkMule ROV | Schilling UHD-III | 4000m | $3–8M | Seabed-node maintenance (essential) |
| Kraken XLUUV | Boeing Orca | 3300m | $40–80M | Autonomous medium |
| Deepcrawler | SMD trencher | 3000m | $15–25M | Fiber-trench, seabed construction |
| Habitat Module | Aquarius Reef Base | 20–30m | $20M build | Persistent seabed base |

#### T3 — Export military (state-authorized)

| Class | Real analog | Displ. | Endurance | Compute | Crew | New price | Lead time |
|---|---|---|---|---|---|---|---|
| Mako-class SSK | Type 209 | 1,200–1,800t | 50 d | 8–12 racks | 30 | $350–500M | 4–6 yr |
| Stingray AIP | Type 212A | 1,800t | 3 wk sub | 10–15 racks | 27 | $700M–1B | 5–7 yr |
| Stingray-X Export | Type 214 | 1,900t | 3 wk sub | 10–15 racks | 27 | $500–800M | 4–6 yr |
| Scorpion-class | Scorpène CM-2000 | 1,700t | 50 d | 10 racks | 31 | $450–700M | 5–7 yr |
| Basalt-class SSK | Kilo 636 | 3,100t | 45 d | 10–20 racks | 52 | $300–400M | 3–5 yr |
| Lada-class | Project 677 / Amur 1650 | 1,700t | 45 d AIP | 10 racks | 35 | $350–500M | 5–8 yr |
| Sirius-class SSK | Sōryū / Taigei-equiv | 4,200t | 6+ wk AIP | 20 racks | 65 | $900M–1.2B | 7–10 yr |
| Liberty-class | KSS-III Dosan | 3,400t | 50+ d AIP | 20 racks | 50 | $900M–1.1B | 6–9 yr |
| Hidalgo-class | S-80 Plus | 2,700t | 3 wk AIP | 15 racks | 32 | $1B | 7–9 yr |
| Sea Dragon | Yuan 039B | 2,700t | 30 d AIP | 15 racks | 38 | $200–350M | 3–5 yr |

#### T4 — Grey market / surplus

| Class | Real analog | Displ. | Condition typ. | Acquisition | Refit cost / time |
|---|---|---|---|---|---|
| Foxglove-class | Foxtrot / Project 641 | 1,950t | stripped hulk | $5–15M | $40–90M, 12–18 mo |
| Romeo-surplus | Project 633 / NK copies | 1,500t | museum-grade | $2–8M | $30–60M, 9–15 mo |
| Basalt-surplus | decom Kilo 877 | 2,300t | alongside-afloat | $40–80M | $80–150M, 12–24 mo |
| Victra-class SSN surplus | decom Victor-III | 6,800t | reactor defueled | $80–150M | $300–600M, 2–4 yr |
| Oscar-class SSGN surplus | Oscar-II | 18,000t | rare | $150–300M | $700M–1.2B, 3–5 yr |
| Delta-class SSBN surplus | Delta-IV | 18,000t | rare | $200–400M | $800M–1.5B, 3–5 yr |
| Typhoon conversion | Project 941 | 48,000t | 1 preserved | $400–800M hull + $1–3B refit | 4–6 yr |
| Sturgeon-surplus | US 637 class | 4,300t | target hulks | $30–60M | $400–700M, 3–5 yr |

Condition grades: `alongside-afloat` / `material-ready reserve` / `stripped hulk` / `target hulk`.

Nuclear hulls almost always arrive **defueled** under non-proliferation treaties. Most grey-market nuclear hulls become diesel-electric or shore-power-tended DC hulks — deniable, immobile, massive.

#### T5 — Specialty / purpose-built

| Class | Real analog | Use | Cost |
|---|---|---|---|
| Seahorse SDV | SDV Mk VIII | Swimmer delivery | $5–10M |
| Proteus DCV | Submergence Proteus | Dual manned/unmanned | $25–40M |
| Sabertooth-class | Saab Sabertooth | Hybrid AUV/ROV | $3–6M |
| Aegis DSRV | LR7, NSRS | Rescue | $40–80M |
| Piranha midget | Ghadir / Yono / CosMos | Coastal covert | $20–50M |
| Triton-midget | Yugo-class | Coastal ops | $40–90M |
| Tempest-habitat | Proteus (Cousteau) | Persistent undersea station | $20–80M |

#### T6 — National strategic (unavailable)

Modern Virginia / Astute / Suffren / Yasen / Borei / Type 212CD — plot-event unlocks only; permanent political consequences.

### 14.3 Typhoon-class (flagship case study)

Project 941 twin-pressure-hull: 175 m × 23 m, 48,000 t submerged. Conversion loadout:
- **Fwd pressure hull** → hardened analyst workspace + encrypted-memory VM cluster (Ibex LPARs)
- **Missile bays** (20 tubes, 16 m tall) → vertical tape silos or Containment-H cells
- **Reactor compartment** → dual OK-650-equivalent plants (~380 MW thermal)
- **Aft** → reduced crew + spares + cooling plant
- **Torpedo room** → retained (see weapons)

Containment +6 from hull steel + seawater Faraday envelope. Deep-water ambient cooling. Reactor power eliminates rationing. Near-invisible submerged outside A2/AD zones. **SPOF:** hull breach = total loss — mirror critical data to land or second hull.

### 14.4 Acoustic / comms at depth

| Posture | Data rate | Stealth | Typical use |
|---|---|---|---|
| Surfaced | Full satcom | Compromised | Resupply window |
| Snorkel + whip | Full satcom | Partial | Emergency |
| Shallow + towed buoy | 1–100 Mbps | Good | Short bursts |
| Deep + ELF | <100 b/s, rx-only | Perfect | "Come up" signals |
| Deep + acoustic modem | 100 b/s – 10 kbps | Perfect, range-limited | Sub-to-sub, seabed |
| Seabed fiber landing | Full fiber | Perfect while docked | Static seafloor base |

A submerged Typhoon runs **write-only** during ops: queue jobs, process for days, brief buoy uplink burst at pre-arranged windows, retract, go deep.

### 14.5 Supply cycles

Three concurrent timers per hull:
1. **Consumables** (O₂ candles, CO₂ scrubber media, food, lube, water) — weeks
2. **Maintenance** (filters, pumps, reactor chem) — months
3. **Dry-dock** (hull survey, welds, sonar) — years

Miss dry-dock → **hull casualty** event risk.

---

## 15. Aerospace

### 15.1 Fixed-wing (crewed)

| Class | Real analog | Role | Range | Payload | Cost | $/hr |
|---|---|---|---|---|---|---|
| Caesna 182-class | Cessna 182 | Commute | 1,500 km | 400 kg | $400k used | $200 |
| Piperline Caravan | Cessna 208 | Light cargo | 1,900 km | 1,400 kg | $2–3M | $500 |
| Twin Utility | DHC-6 Twin Otter | Austere-strip | 1,500 km | 1,900 kg | $6–10M | $1,200 |
| Amphibian | CL-415 | Water access | 2,400 km | 6,100 kg | $30M | $3,500 |
| Goldstream G650 | Gulfstream G650 | Exec transport | 13,000 km | 8 pax | $65M | $5,000 |
| Broadsword Global | Bombardier Global 7500 | Long-range + secure comms | 14,000 km | 14 pax | $75M | $6,000 |
| Herald-class | C-130J Hercules | Austere cargo | 3,800 km | 19 t | $70M | $8,000 |
| Bolderhaul-A400 | A400M | Medium-heavy cargo | 6,400 km | 37 t | $150M | $13,000 |
| Titanlift-17 | C-17 Globemaster III | Strategic heavy, MobiDC | 4,500 km | 77 t | ~$250M | $24,000 |
| Leviathan-124 | An-124 | Outsized cargo | 4,000 km | 120 t | charter only | $25–50k |
| Oceanhawk MPA | P-8 Poseidon | Maritime patrol + SIGINT | 8,000 km | 9 t sensors | $250M | $12,000 |

### 15.2 Rotary-wing

| Class | Real analog | Role | Range | Payload | Cost |
|---|---|---|---|---|---|
| Lightfoot-407 | Bell 407 | Exec, small team | 600 km | 6 pax | $4M |
| Leonidas AW139 | AW139 | Mid-utility | 1,000 km | 15 pax | $17M |
| Sycamore S-92 | Sikorsky S-92 | Heavy offshore / SAR | 1,000 km | 19 pax | $28M |
| Warhorse-UH | UH-60 Black Hawk | Tactical insert | 600 km | 11 pax | $20M |
| Heavyhaul CH-47 | CH-47 Chinook | Heavy-lift | 750 km | 12 t sling | $35M |
| Heavyhaul Mi-8 | Mi-8/17 | Rugged utility | 600 km | 4 t | $8–15M used |
| Heavylift Mi-26 | Mi-26 | Full 20-ft container sling | 800 km | 20 t | $25M used |

### 15.3 UAV — tactical / MALE / HALE

| Class | Real analog | Role | Endurance | Range | Cost |
|---|---|---|---|---|---|
| Avion Ranger | AV Puma | Hand-launched recon | 3 h | 20 km | $15–40k |
| Drona M-series | DJI Matrice 350 RTK | Short-range mapping | 55 min | 20 km | $15k |
| Switchblade-analog | Switchblade 300 | Loitering | 15 min | 10 km | $60k/ea |
| V-BAT-class | Martin V-BAT | VTOL fixed-wing | 8–11 h | 350 km | $1M |
| Skyhand TB-2 | Bayraktar TB2 | MALE | 27 h | satlink 4,000 km | $5M |
| Skyhand Akinci | Bayraktar Akıncı | Heavy MALE | 24 h | same | $30M |
| Universal Reaper-class | MQ-9 Reaper | Long-endurance ISR + strike | 27 h | 1,800 km | $32M |
| Universal Mojave | MQ-9B Mojave | STOL Reaper | 27 h | 1,800 km | ~$25M |
| Northmoor Globeguard | RQ-4 Global Hawk | HALE ISR | 34 h | 60,000 ft | $130M |
| Northmoor Triton | MQ-4C Triton | Maritime HALE, sub-relay | 30 h | 56,000 ft | $180M |

### 15.4 HAPS (High-Altitude Pseudo-Satellites)

| Class | Real analog | Endurance | Altitude | Cost |
|---|---|---|---|---|
| Zephyra S | Airbus Zephyr 8 | Months | 70,000 ft | $15M + ground |
| Stratollite-class | World View Stratollite | Weeks–months | 75,000 ft | $5M per mission |
| Skyhab airship | Sceye / HAV Airlander | Days–weeks | 20,000–65,000 ft | $40M |

### 15.5 Ship-launched UAVs

| Class | Real analog | Host |
|---|---|---|
| Seaforge ScanEagle | Insitu ScanEagle | Any ship w/ deck |
| Tern-class VTOL | Northrop Tern / MQ-8 Fire Scout | OSV, research vessel |

### 15.6 Mission pallets (roll-on/roll-off)

| Pallet | Compatible airframes | Function |
|---|---|---|
| SIGINT suite | Herald, Oceanhawk, Reaper | Signals intel + onboard quarantined-VM |
| Comms relay node | Any MALE/HALE, Zephyra | Airborne satcom + mesh gateway |
| Blue-green laser sub-link | Oceanhawk, Triton, Zephyra | Bridges submerged fleet at speed |
| ELF transmitter | Modified Herald (TACAMO-analog) | Deep-sub "come up" orders |
| Hyperspectral / LIDAR | Caravan, Reaper | Anomaly site survey |
| Atmospheric sampler | Caravan, Skyhand | Airborne memetic/chem detection |
| Mnestic aerosol dispersal | Caravan, helicopters | Area cognitohazard counter (ethics flag) |
| MEDEVAC | Herald, Mi-8 | Staff recovery |
| Cargo standard | Any with cargo door | Containers |
| VIP / bunk | Herald, A400M | Long-mission crew |
| Tanker kit | Herald | Air-to-air refuel |
| Drop container | CH-47, Mi-26 | Full MobiDC to austere site |

### 15.7 Airfields & aviation infra

| Tier | Cost | Exposure |
|---|---|---|
| Public airport tie-down | $5k/mo | Full |
| Public airport hangar | $15–50k/mo | Some discretion |
| FBO contract | Varies | Low |
| Owned private airfield | $20–80M build | Full control |
| Austere/dirt strip | $500k prep | Seasonal |
| Military/allied access | Political favor | Dependency |

### 15.8 Airborne relay as killer app

HALE UAV or HAPS orbiting over submerged assets' AO, carrying blue-green laser + ELF → your Typhoon receives burst-upload orders without trailing an antenna. Latency < 60 ms for shallow ops enables real-time C2 for subs.

### 15.9 Stealth & airspace

- ADS-B on = fully public (enthusiast trackers). OPSEC nightmare.
- ADS-B off in controlled airspace = criminal.
- Low-RCS airframes + terrain-masked routing reduce detection, don't eliminate.
- HAPS at 70,000 ft are above traffic but tracked by most national radars.
- Flight plans leak; false destinations mostly illegal.

Radar visibility is a fleet-wide consideration — an asset's transit history can be reconstructed retroactively after a breach.

### 15.10 Aviation risk

- GA crash rate ~6 per 100k flight hours; budget for it.
- UAV loss rate much higher (~2 per 10k hr historically).
- Single-engine UAVs have no redundancy.
- HAPS vulnerable to weather excursion.
- Downed asset recovery is its own logistics event (or remote self-destruct, research unlock).

### 15.11 Orbital infrastructure — overview

Space is the fourth transport / comms layer (after ground / sea / air). Owning orbital assets buys three things the other layers cannot:

1. **Covert routing.** Your own comms satellite bypasses commercial provider metadata — a Starstream subscription leaks traffic patterns; a privately-owned satellite does not.
2. **Persistent ISR.** Continuous imagery / SIGINT / ELINT coverage without a flight crew.
3. **Genuine air-gapped compute/storage.** Orbit is the most physically isolated location available short of subsea cable-islanded pods, with the added benefit that nobody can walk up to it.

All satellite assets share the modular bus + payload pattern (unifies with sub and aerospace modular designs from §20).

### 15.12 Satellite bus classes

| Bus | Real analog | Mass class | Payload budget | Power (EOL) | Lifetime | Bus cost |
|---|---|---|---|---|---|---|
| **QuantumCube 1U** | 1U CubeSat | 1 kg | 0.4 kg / 2 W | 2 W | 1–2 yr | $50k |
| **QuantumCube 3U** | 3U (Planet Dove) | 4 kg | 2 kg / 10 W | 15 W | 2–3 yr | $250k |
| **QuantumCube 6U** | 6U CubeSat | 10 kg | 5 kg / 30 W | 40 W | 3–5 yr | $800k |
| **QuantumCube 12U** | 12U CubeSat | 20 kg | 12 kg / 80 W | 100 W | 3–5 yr | $2M |
| **Nimbus Small** | ESPA-class (Capella SAR) | 150 kg | 80 kg / 500 W | 800 W | 5–7 yr | $8M |
| **Nimbus Medium** | 500 kg bus (Iridium NEXT) | 500 kg | 250 kg / 2 kW | 3 kW | 10 yr | $25M |
| **Polaris Large** | GEO heritage bus | 3,500 kg | 2,000 kg / 12 kW | 18 kW | 15 yr | $120M |
| **Polaris XL** | Heavy GEO (Inmarsat-6) | 6,500 kg | 4,200 kg / 18 kW | 25 kW | 15+ yr | $220M |
| **OTV-class** | X-37B analog | 5,000 kg | 900 kg bay | hours–years | **reusable** | plot-gated, ~$500M access |

Bus prices are hardware only — add integration, test, insurance, and launch.

### 15.13 Payload modules

Bus-agnostic within mass/power/pointing budgets. Research unlocks advanced variants (cf. §19 Comms and AI domains).

| Category | Module | Mass | Power | Use |
|---|---|---|---|---|
| Comms | UHF/VHF transponder | 2 kg | 10 W | Low-BW telemetry, command |
| Comms | L-band broadcast | 8 kg | 30 W | Voice + narrowband data |
| Comms | Ku-band transponder | 25 kg | 150 W | High-BW narrow-beam |
| Comms | Ka-band multi-beam | 80 kg | 400 W | Multi-Gbps regional |
| Comms | V-band / laser crosslink | 30 kg | 100 W | Inter-sat + ground laser, hardest to intercept |
| Storage | Rad-hard SSD array (small) | 10 kg | 20 W | ~50 TB air-gapped |
| Storage | Rad-hard SSD array (large) | 50 kg | 80 W | ~500 TB |
| Compute | Edge NPU (Tenstorrent-analog) | 6 kg | 60 W | On-orbit inference |
| Compute | Rad-hard AI accelerator | 40 kg | 300 W | Heavy batch compute |
| SIGINT | Wideband RF receiver | 15 kg | 80 W | Signal collection |
| SIGINT | DF / geolocation array | 40 kg | 200 W | Emitter triangulation |
| ELINT | Emitter-catalog processor | 15 kg | 60 W | Cross-sat correlation |
| IMINT | 0.5 m EO imager | 100 kg | 400 W | Daylight optical |
| IMINT | Sub-meter SAR | 120 kg | 500 W | All-weather |
| IMINT | Hyperspectral | 60 kg | 250 W | Chemical / memetic signature detection |
| IMINT | IR / thermal | 40 kg | 200 W | Night + breach signature |
| Defense | Decoy / countermeasures | 10 kg | 20 W | Anti-ASAT (limited) |
| Propulsion | Electric thruster kit | 15 kg | 600 W | Station-keeping + maneuver |

Constraints on a composed satellite:
- `sum(module_mass) ≤ bus.payload_mass`
- `sum(module_power) ≤ bus.payload_power_eol`
- Some modules are orbit-locked (SAR needs LEO; GEO transponder needs GEO)
- Pointing payloads (IMINT) consume reaction-wheel budget and can't share with large comms dishes on the smallest buses

### 15.14 Orbit tiers

| Orbit | Altitude | Coverage | Best for | Ground latency |
|---|---|---|---|---|
| **LEO** | 400–2,000 km | Spot, ~10 min/pass | IMINT, SIGINT, tactical ISR | 2–10 ms |
| **SSO** (polar sun-sync) | 600–800 km | Twice-daily polar | Imagery with consistent lighting | 2–10 ms |
| **MEO** | 2,000–20,000 km | Regional | GPS-like nav, mid-coverage comms | 30–70 ms |
| **GEO** | 35,786 km | Fixed over longitude | Wide-area broadcast, persistent comms | ~240 ms one-way |
| **HEO** (Molniya) | 600 × 39,000 km | Northern polar dwell | High-latitude comms | varies |
| **Cislunar** | ≥ 384,400 km | Deep space | Specialist storage / exotic ops | 1.3 s+ |

Orbit gates what a payload can do — a SAR in GEO is useless (too far for resolution); a LEO GEO-comms transponder swaps footprints every 10 min.

### 15.15 Launch vendors

Prices are per-launch unless noted. Trademark-safe renames; realistic 2026-ish economics.

| Vendor | Vehicle | LEO capacity | LEO price | Notes |
|---|---|---|---|---|
| **SpaceTech** | Falcon-9 analog | 22.8 t | $67M | Workhorse; reliable |
| **SpaceTech** | Falcon-Heavy analog | 63.8 t | $97–150M | Heavy |
| **SpaceTech** | Starship analog | 100+ t | $150M (projected) | Reusable, cheap/kg |
| **SpaceTech Transporter** | rideshare | 300 kg slots | $6k/kg | LEO-only, slot-constrained |
| **RocketForge** | Electron-analog | 300 kg | $7.5M | Dedicated small-sat |
| **RocketForge** | Neutron-analog | 13 t | $55M | New medium |
| **UnionLaunch** | Vulcan Centaur analog | 27.2 t | $110M | Trusted heavy alt |
| **BlueHorizon** | New Glenn analog | 45 t | $90M | Reusable heavy |
| **Arianex** | Ariane 6 analog | 21.6 t | $115M | European |
| **Firelight** | Firefly Alpha analog | 1 t | $15M | Small-med |
| **Oriental Space** | Long March 8 analog | 5 t | $30M | Budget; **permanent political heat** |
| **Vostok Launch** | Soyuz-2 analog | 8.2 t | $48M | Legacy; **political heat** |
| **Indian Space** | LVM3 analog | 8 t | $70M | Stable, politically-neutral option |

Price multipliers by orbit:
- LEO baseline · SSO +10% · GTO ×2.5 · GEO direct ×3.5 · cislunar ×5

Other modifiers:
- **Rush slot** (<3 months): +50%
- **Rideshare vs dedicated**: rideshare ~30–50% of dedicated per kg, but schedule-constrained
- **Export politics**: Oriental Space and Vostok carry permanent flag-of-launch metadata that adversary intel correlates

Lead times:
- Rideshare slot: 6–18 months queue, then a 2-month launch window
- Dedicated smallsat (Electron): 3–9 months
- Dedicated medium-heavy (Falcon-class): 6–18 months
- GEO campaign (Ariane 6 dedicated): 12–24 months
- OTV / reusable (X-37-class): plot-gated, 2+ years

### 15.16 Ground stations & portable antennas

Owned satellites require ground terminals to uplink commands and downlink data. A satellite with no reachable ground station is a brick.

| Tier | Real analog | Capex | Build time | Role |
|---|---|---|---|---|
| **Rented pass** | AWS / KSAT / Viasat | $0 capex, $k/pass | immediate | Cheap start; third-party sees traffic metadata |
| **Portable uplink** | Kymeta / flat-panel phased | $120k each | 1 week | Field-deployable comms terminal |
| **Fixed small dish** | 3 m Ka/Ku | $500k | 2–4 weeks | Site-local uplink |
| **Fixed medium** | 7–9 m station | $2M | 3–6 months | High-BW LEO/GEO |
| **Deep-space large** | 13 m+ with cryo LNAs | $15M | 12–18 months | GEO high-BW + exotic orbits |
| **Phased-array flat** | Starlink-style tracking | $8M | 6 months | Tracks multiple LEO sats simultaneously |

Commandability rules:
- Every owned satellite must be within sight of at least one capable ground station to receive commands
- GEO is permanently in sight of its footprint; LEO appears in short passes (~10 min each)
- Miss a planned pass and commands queue until next pass
- Ground-station compromise (physical raid) = adversary can take control of your satellite — mitigated by HSM key storage (research unlock)

### 15.17 OTV-class reusable (X-37 analog)

Real analog: Boeing X-37B. Classified USSF operator; two airframes; missions from 200 to 900+ days; payload bay; reusable.

In-game (**OTV-class Orbital Test Vehicle**, renamed for trademark):
- **Acquisition**: plot-gated. Foundation-scale diplomacy at the same tier as the Typhoon-class arc.
- **Capex / access**: ~$500M for a program slot; no open market.
- **Mission cost**: $15–30M per flight (launch + ops).
- **Payload bay**: ~900 kg, modular pallets (shares the pallet bus with sub/air per §20).
- **Unique capabilities**:
  - **Return payloads to Earth** — physically recover an orbital asset, including quarantined physical media, without intermediaries. Irreplaceable for some Foundation arcs.
  - **In-orbit deploy** — release cubesat fleets without a dedicated launch.
  - **On-orbit maintenance** — recapture, service, redeploy small satellites.
  - **Reusable** — no full refurb between missions (unlike capsules).

Thematically: this is the endgame covert orbital asset. Ownership is a multi-season commitment.

### 15.18 HAPS / airships as interim coverage

HAPS (§15.4 Zephyra, Stratollite) and rigid airships (Skyhab) serve as the **bridge** between "we need coverage now" and "launch slot in 9 months."

| Asset | Lift time | Dwell | Best role |
|---|---|---|---|
| Zephyra HAPS | days | weeks–months | Regional comms relay, persistent ISR pre-satellite |
| Stratollite balloon | 1 day | weeks | Station-keeping over a specific AO |
| Skyhab airship | days | days–weeks | Low-altitude relay, heavier payload than HAPS |

Strategic implication: **balloons/airships are tactical**, **satellites are strategic**. During a 6-month satellite delivery window, HAPS provide interim capability at ~5–20× cheaper per coverage-month, at lower stealth and lower bandwidth.

### 15.19 Orbital gameplay integration

Concrete mechanical effects of owned orbital assets:

| Asset | Mechanical benefit |
|---|---|
| **Comms satellite (owned)** | Unlocks "private satcom" tier — bypasses provider metadata; +1 to `network_stealth_class` per asset; latency depends on orbit |
| **Storage satellite** | Extreme air-gap archive; items stored here are unreachable by any terrestrial GOI raid (physical retrieval via OTV only); high lifetime risk |
| **Compute satellite** | Bulk-batch analysis offload; no terrestrial power constraints; latency-limited to high-latency-tolerant workloads |
| **SIGINT satellite** | Adds a new scan source class — intercepts anomalous RF signatures with global reach |
| **ELINT satellite** | Tracks rival-GOI emitters → improves your threat-intel fog |
| **IMINT (EO)** | Breach-site visual overwatch |
| **IMINT (SAR)** | All-weather site monitoring including hostile AO |
| **IMINT (hyperspectral)** | Detects chemical / memetic signatures of anomaly release |
| **IMINT (IR)** | Night + thermal; detects concealed facilities or active compute clusters |
| **OTV-class** | Retrieve physical items from orbit; covertly deploy classified smallsats |

Pairings:
- **Sub + laser-equipped LEO comms sat + portable uplink** → a submerged hull receives burst C2 via laser downlink to a trailing buoy, no surface emissions at all
- **Antarctica base + polar LEO SAR** → continuous monitoring of your remote polar AO
- **Foundation citadel + GEO comms sat + deep-space ground station** → permanent private comms independent of commercial providers
- **OTV + rad-hard SSD array** → retrieve a decade of cosmic-ray-sanitized archive to Earth on a scheduled recovery flight

### 15.20 Orbital risk & failure modes

- **Launch failure** — 2–5% depending on vehicle maturity; total payload loss
- **Early-orbit commissioning failure** — ~5% of satellites fail in the first 90 days (deployment, solar array, pointing)
- **Component degradation** — lifetime-limited; EOL derating at 50%+ of designed budget
- **Collision / debris strike** — low probability per orbit-year but catastrophic outcome; Kessler-cascade risk in extreme plot lines
- **ASAT event** — state-actor hostility; extremely rare without narrative cause, but modelable
- **Cover exposure** — unusual satellite patterns draw adversary SIGINT; uplink pattern analysis can de-anonymize ground stations
- **Ground station compromise** — physical raid yields uplink keys; mitigated by HSMs + key rotation (research)

---

## 16. Autonomous systems & redundancy

### 16.1 Autonomy levels

- **Assisted** — operator at console, autonomy aids
- **Supervised** — periodic operator checks
- **Autonomous / attended** — humans available remote
- **Autonomous / unattended** — no humans, mission duration

### 16.2 N+k redundancy requirement (autonomous)

| Mission length | Required redundancy | Examples |
|---|---|---|
| < 72 h | N+1 | Propulsion motor, comms path |
| 1–4 weeks | N+2 | + Cooling pumps, power conversion, nav |
| 1–3 months | N+2 + auto damage control | + Fire/flood, battery isolation |
| 3+ months | N+2 + auto DC + graceful degradation | Asset useful at 40% capacity |

### 16.3 Rack-level

Autonomous compute uses **3× hot spare ratio** so a failed server fails over silently. Model server MTBF honestly (~1 failure per 1,000 server-months) — a 50-rack autonomous XLUUV sees a failure ~every 10 days.

### 16.4 Loss mode

Autonomous boat dark → unknown cause. Recovery (crewed boat to last-known position) is a logistics event. Captured autonomous platforms are an intel loss to rival GOIs.

---

## 17. Staff (all lanes)

### 17.1 Roles (separate labor pools)

- **Ops / IT**: Analyst, SysAdmin, ML Engineer, Memeticist, Forensics Tech, Field Agent
- **Logistics / electrical**: Logistics Officer, Electrician, HVAC Tech
- **Science**: Principal Investigator (PI), Research Staff, Lab Tech, Postdoc
- **Aviation**: Fixed-wing Pilot, Rotary Pilot, UAV Operator, A&P Mechanic, Avionics
- **Maritime**: Captain, Deck Officer, Engineer, Reactor Op (nuclear subs), Deck Crew
- **Security**: Counterintel, Armed Response, PMSC Contractor

### 17.2 Attributes per employee

```
employee = {
  id, name, role, skills{...}, clearance_level (0–5),
  certifications[], currency_dates{...},
  salary, burnout (0–100), loyalty (0–100),
  clearance_history, incident_history,
  training_in_progress[], current_assignment,
}
```

### 17.3 Lifecycle

`recruit → classroom train → on-job XP → certify → field-cert (if applicable) → senior → retire/defect/casualty`

### 17.4 Recruitment channels

- Academia (slow, credentialed, expensive)
- Industry poach (fast, premium, burnout risk)
- Foundation internal transfer (free, thins other sites)
- Ex-GOI defector recruitment (risky, possible sleeper)

### 17.5 Field cert

Separate track from technical skills. Uncertified staff sent to a site perform poorly and can be lost in breaches.

---

## 18. Training, clearances, pager, delegation

### 18.1 Training curricula (research can add more)

| Course | Duration | Prereq | Unlocks |
|---|---|---|---|
| Analyst entry | 4–8 h | — | Safe-class handling |
| Memeticist L1 | 2 days | analyst entry | Euclid-class handling |
| Memeticist L3 | 3–5 days | L1 | Keter-class handling |
| Field cert | 2–3 days | — | Deploy to sites |
| Reactor operator | 4–8 weeks | engineering bg | Crew nuclear hulls |
| Type-rating (per airframe) | 2–3 weeks | pilot license | Fly that airframe |
| Mnestic protocol | 4 h | memeticist L1 | Participate in post-exposure debrief |

### 18.2 Clearance levels 0–5

Gating which items, sites, and reports staff can interact with. Clearance history persists per-person.

### 18.3 Playbooks / standing orders (first-class)

Player authors rules:
```
when item.class == Euclid and memetic_load > 5:
    if encrypted_vm_available:
        analyze with isolation=encrypted
    else:
        archive to tape; page on-call memeticist
```

### 18.4 Delegation authority

Per employee, per domain: `observe` / `act-within-budget` / `act-unrestricted`.

### 18.5 Pager

Severity ladder: `INFO / NOTICE / WARNING / ALERT / BREACH`.

Configurable channels:
- OS desktop notifications (baseline)
- Email / SMS (Twilio, Mailgun)
- Discord / Slack webhook (thematic)
- Pushover / ntfy (mobile)

Quiet-hours rules. Only ALERT+ pages at night by default.

### 18.6 The 3-AM test

A breach at 3 AM local should be survivable if playbooks + delegation + staffing coverage are well-designed. If the player is paged, the event is one the playbook explicitly flagged for human decision — not a failure of the system to cope without you.

---

## 19. Research & development

### 19.1 Project model

```
project = {
  domain, prerequisites, duration_base,
  PI_skill_required, team_slots,
  lab_type_required, equipment_required,
  budget_total, budget_burn_per_day,
  risk_profile, outputs,
}
```

Milestones at 25/50/75/100%. Missed milestone → status event (delay, pivot, quiet failure, catastrophic incident).

### 19.2 Lab tiers

| Tier | Facility | Capacity | Cost |
|---|---|---|---|
| T0 | Office whiteboard | 1 slot | free |
| T1 | Bench lab | 2–3 slots | $2–5M + $20k/mo |
| T2 | Specialty lab | 4–6 slots | $15–40M + $150k/mo |
| T3 | Multi-discipline R&D campus | 12–20 slots | $150–400M + $1M+/mo |
| T4 | Hazmat / memetic range | 2–4 slots | $80–200M + $500k/mo |
| ** | Prototype shop | separate | $30–120M |

Labs have **location effects**: AI lab near fiber = faster, memetic lab underground = safer.

### 19.3 Domains & sample nodes

| Domain | Starter | Mid | Endgame |
|---|---|---|---|
| Naval Architecture | Modular hull bus v1 | Compute bay modules | Pressure-hull interlock (at-sea swap) |
| Containment | Software mem encryption | Hardware SEV-analog | Homomorphic VM (analyze encrypted) |
| Power | LFP banks | AIP fuel cell v2 | Molten-salt microreactor |
| Comms | Phased-array VSAT | Blue-green laser buoy | QKD over fiber |
| AI / Detection | Custom memetic classifier | Adversarial-robust scanner | Foundation FM for classification |
| Materials | Anechoic tile v2 | Mnestic-shielded alloy | Metamaterial memetic absorber |
| Biosci | Mnestic refinements | Durable amnestics | Cognitohazard-resistant operator UI |

### 19.4 Power / comms / detection research tables

**Power:**
| Project | Prereq | Duration | Output |
|---|---|---|---|
| LFP chem | — | 2 mo | +30% density, -40% fire risk |
| H₂ fuel cell AIP | battery v1 | 5 mo | +60% submerged endurance |
| OTEC pod | materials I | 8 mo | Free low-grade power (Panthalassa) |
| RTG (small field) | materials II, nuclear | 10 mo | 100W–2kW, 10 yr, remote autonomy |
| MSR microreactor | nuclear II | 18 mo | 5–20 MW, cheaper, air-coolable |
| sCO₂ turbines | materials II | 8 mo | +15% reactor efficiency |

**Comms:**
| Project | Duration | Output |
|---|---|---|
| Phased-array VSAT | 3 mo | Submerged snorkel-depth 100+ Mbps |
| Blue-green laser | 7 mo | 10+ Mbps to shallow-sub buoy |
| Improved acoustic modem | 5 mo | Sub-to-sub 50 kbps @ 10 km |
| QKD over metro fiber | 12 mo | Crypto-isolated site pairs |
| Swarm mesh protocol | 4 mo | UUV fleet w/o central link |
| Your own LEO constellation | very long | Moonshot |

**Aerospace:**
| Project | Duration | Output |
|---|---|---|
| Autonomous flight controller v2 | 6 mo | Lower UAV loss rate |
| Solar HAPS airframe | 18 mo | Homegrown Zephyra |
| Airborne blue-green laser | 10 mo | HAPS ↔ sub link |
| Hyperspectral memetic detector | 9 mo | Aerial anomaly detection |
| Quiet long-endurance airframe | 14 mo | Reduced signatures |
| Aerial mnestic dispersal | 12 mo | Area cognitohazard counter (ethics) |
| Modular mission-pallet std. | 4 mo | Cross-fit pallets |

### 19.5 Failure modes per domain

| Domain | Worst-case |
|---|---|
| Memetics | PI cognitohazarded; findings contaminated; team needs amnestics |
| Materials | Prototype failure; physical lab damage |
| AI | **Infected model** — quietly corrupts advice until detected |
| Power / nuclear | Excursion event; regulatory scrutiny |
| Bioscience | Mnestic side effects; permanent memory loss in volunteers |
| Comms | Inadvertent broadcast of quarantined data |
| Crypto | Scheme breaks under scrutiny; years of archive retroactively weak |

### 19.6 Publication vs classification

On completion, choose:
- **Publish** — prestige ↑, recruitment ↑, grant ↑, GOI spillover
- **Foundation-internal** — other Foundation teams benefit, modest prestige
- **Level-4 classified** — you only, no prestige, no spillover

### 19.7 Technology leakage

- Scientist defection
- Lab raid
- Supply chain compromise
- Inadvertent conference talk

Counter-investment: CI staff, hardened labs, air-gapped lab networks, mandatory amnestic review of departing staff (ethics flag).

---

## 20. Modular design language

### 20.1 Hull bus standard

Research produces interface standards — power / cooling / data / mechanical. Any module compliant with `Bus Std. vN` fits any compliant hull. Version mismatches require adapter modules (weight + power cost).

### 20.2 Module categories

| Category | Sample modules (research-unlocked) |
|---|---|
| Propulsion | Diesel-electric v1/v2, AIP fuel cell, Pumpjet, Shrouded prop, Electric pod |
| Power | LFP small/med/large, Li-S, Micro PWR, SMR, RTG (small), Thermoacoustic |
| Compute bay | Small (2 racks), Medium (8), Large (16), Mainframe compartment |
| Storage bay | Tape vault small/large, Spinning-disk bulk, Cold archive |
| Comms mast | VSAT, Phased-array, Laser buoy, Acoustic modem array, ELF rx |
| Containment cell | Soft (shielded room), Medium (Faraday + mnestic), Hard (SCSC) |
| Habitability | Berthing 8/24/60, Galley, Medical bay, Long-duration autonomous |
| Sensors | Passive sonar, Active array, Optical, Magnetic anomaly, Memetic field |
| Defense | Decoy launcher, Countermeasure ejector, Torpedo tubes, Anti-swimmer |
| Utility | Workshop, ROV garage, Dive lock-out, Reactor aux, Cooling plant |
| Refit interface | Pressure-hull interlock (at-sea module swap) |

### 20.3 Slot map per hull

Each hull class exposes physical slots with engineering constraints (weight, power, cooling, volume, structural). Example (abbreviated):

```
Typhoon-conversion:
  fwd pressure hull:  [Hab] [Compute-L] [Compute-L] [Containment-H]
  missile deck:       [Storage-tape] × 20 silos
  reactor compt:      [Power-SMR] × 2  (baseline, not cheap to swap)
  aft:                [Workshop] [Sensors] [Defense-opt]
  sail:               [Comms-phased] + [Comms-laser] + [Sensors]

Kraken XLUUV:
  forward:   [Sensors] [Comms-mast]
  midbody:   [Compute-S] + [Power-LFP]  OR  [Compute-M] + [Power-AIP]
  aft:       [Propulsion-pod]
```

### 20.4 Refit = redesign

Every dry-dock is a chance to re-lay the module map. Research unlock in Q2 → fleet refit by Q4. Pressure-hull interlock (late research) enables at-sea swaps.

### 20.5 Pallet unification (sub vs. air)

Open decision — see §27 — whether sub modules and air mission pallets share a single modular standard or remain separate research branches.

---

## 21. Logistics, contracts, markets

### 21.1 Transport layers

- **Ground** — truck, rail; cheap, slow, most visible
- **Sea** — ship, sub, UUV; slow, least visible, long endurance
- **Air** — plane, heli, UAV; fast, expensive, medium-visible
- **Data-link** — encrypted site-to-site transmission of archived items.
  No physical logistics. Duration scales with the slower of the two sites'
  network bandwidth; cost = flat handshake + $100/GB. Gated by an
  encryption floor keyed to item hazard class (Safe → software, Euclid →
  hardware, Keter → type1). Destination must have tape headroom for the
  payload. Best for consolidating archived libraries onto high-security
  sites (subsea pod, underground bunker, Antarctica) without exposing
  physical tapes to ambushes, sea pirates, or customs inspection.

### 21.2 Contracts

Every recurring input is contracted:
- Power: grid utility, fuel suppliers
- Comms: ISP, satcom provider, fiber lease
- Supplies: consumables, parts, chemicals
- Colo: rack/U lease
- Insurance: hull, aviation, liability
- PMSC: crew protection
- Scanner/mnestic signature feeds: live threat intel

Each contract has term, price-lock, take-or-pay, SLA, political risk.

### 21.3 Contract lapse = mistake vector

Stale scanner DB → unnoticed exposure. Late fuel → brownout → corrupted analysis. Canceled comms feed → blind spot.

---

## 22. Refit yards & acquisition projects

### 22.1 Hull acquisition as a project

1. **Broker contact** — logistics skill gates access tier
2. **Hull survey** — Argonaut AUV or diver team; poor survey → you don't know what you're buying
3. **Purchase negotiation** — price, provenance, flag-of-convenience
4. **Tow / transit** — nuclear hulls often can't move under own power
5. **Refit yard slot** — ~6 yards worldwide can work on nuclear; waiting lists
6. **Refit execution** — real weeks to years; milestone inspections; overrun risk
7. **Sea trials** — failures return to yard

### 22.2 Leasing

State-like entities can lease (cf. India leasing an Akula). Cheaper upfront, higher ongoing, political dependency, recall-in-crisis risk.

### 22.3 Refit yards as constraint

~3–4 named nuclear-capable yards in-game. Civilian yards handle SSKs. **Yard relationship** is a multi-year reputation stat:
- Good relationship → priority slots
- Burned yard → blacklist for years
- Cover-identity alignment gates which yards will work with you

---

## 23. Economy & funding

### 23.1 Sources

- **O5 baseline funding** — scales with site portfolio + classified archive size
- **Milestone grants** — containment successes, research publications
- **Internal transfer revenue** — selling analysis to other Foundation teams
- **Research commercialization** — publish-path unlocks civilian grants
- **Unsanctioned revenue** — high risk, flagged (e.g., selling stale tech to grey market)

### 23.2 Expenses

- Staff salary + burnout mitigation
- Power / fuel / cooling
- Contracts (comms, supplies, insurance)
- Capex depreciation
- Refit / maintenance budgets
- Research burn
- Pager channel subscriptions (nominal)

### 23.3 Curves

Non-exponential. Force trade-offs: I300 pod vs. subsea pod vs. mainframe refit. Large capex hits (new site, mainframe, SMR, hull acquisition) take months of saving + financing events.

---

## 24. Threats, GOIs, events

### 24.1 Threat actors (agent-based where feasible)

- **Chaos Insurgency** — theft, sabotage, defector recruitment of your scientists
- **Marshall Carter & Dark** — mercenaries, arms for hire, interested in your archive
- **Global Occult Coalition (GOC)** — hostile when your cover slips
- **State intel services** — ambient detection, political heat
- **Pirates / criminal** — opportunistic against ships
- **GOI-internal rivalries** — exploitable

### 24.2 Event types

- **Breach** — contained item wakes up
- **GOI raid** — kinetic attempt on a site/asset
- **Breach propagation** — infection spreading network-internal
- **Inspection** — treaty / regulatory / yard audit
- **Supply disruption** — contract failure, fuel crisis
- **Political** — flag-of-convenience state changes policy
- **Environmental** — storm, hurricane, earthquake affecting sites
- **Research milestone** — own or rival
- **Insider** — defection, blackmail, contamination via staff
- **Intelligence** — bounty from O5, GOI window of opportunity

### 24.3 Rhythm

- Daily: shift-change reports, anomaly digests
- Weekly: O5 funding review, payroll, contract renewals
- Monthly: audits, clearance reviews, hardware depreciation
- Irregular: breaches, raids, supply disruptions (pager-worthy)

### 24.4 Adversary intel (fog of war, both ways)

Open decision (§27) — do GOIs track your assets with imperfect intel, mirroring your fog over them?

### 24.5 Combat & field-ops mechanics (deferred — planned Phase 12+)

Aircraft, ships, and submarines currently exist as cargo-transport and basing
assets. The design intent is to give each a distinct operational role beyond
hauling containers, all expressed as scheduled tasks with skill/risk rolls:

**Site security rating.** Each site has a numeric `security_rating`
computed from:

- Physical assets on-site: armed PMSC contracts, MTF squads, perimeter drones,
  aircraft patrols overhead, ships/submarines offshore, hardened shelter tier
  (tent → office_closet → bunker_shallow → underground → oil_platform →
  subsea_pod → antarctica).
- Current infiltrator count — enemy agents placed by GOIs reduce the effective
  rating. Counterintel staff + periodic sweeps find and remove them.
- Network hardening (encryption level + IDS posture + air-gap).
- Rating gates: GOI raid rolls, defection attempts, external scan leaks.

**Infohazard outbreaks.** A failed containment (scan bust, VM escape,
archive-leak) can seed an outbreak at the site. Outbreaks have:

- Detection radius (miles) — grows over time if uncontained.
- Memetic signature — specific to the infohazard's class/strength.
- Casualty / reputation damage per tick.

**Surveillance aircraft** (MPA, HAPS, ISR UAV, JSTARS-class AEW) can be
tasked to monitor regions. Their sensor radius and loiter time determine how
fast outbreaks are detected. Higher-tier sensors see memetic/anomalous
signatures invisible to civilian satellites.

**Field agent dispatch.** MTF squads can be airlifted (helo, tiltrotor, C-130
airdrop) or sealifted (RHIB, LCAC) to outbreak sites. Field operations roll
against: MTF training, gear, SCP hazard strength, local terrain. Outcomes:
contained / partial / failed / casualties / exposure.

**Deployable portable container DCs.** MobiDCs and containerized compute pods
can be air-dropped or ship-delivered to outbreak sites to run local scanners
and stand up a forward VM rack for real-time analysis. Acts like a temporary
site with its own power/cooling/network (often starstream or LTE).

**Submarines as ultra-secure storage.** SSBN-class and Typhoon-class hulls
converted to archive pods — highest-tier physical shielding, mobile, hard to
locate. Only suitable for the most dangerous archived SCPs (Keter / heavy
memetic). Very limited capacity, very high operating cost, very long
transit for retrieval.

**Submarine ISR on rival naval assets.** SSN/SSGN + towed array → track GOI
ships and SSBNs. Intel outputs: position updates, acoustic fingerprints,
payload hints. Feeds the adversary-intel fog-of-war system (§24.4).

**Infohazard-derived intel.** Successful analysis of certain infohazards
yields intel on rival GOIs: known personnel, site locations, security
postures, equipment rosters. This seeds the targeting data for:

**MTF assault on rival GOI sites.** Late-game capability requiring
multi-domain planning: ISR (where is the site + security level) → insertion
(airborne or amphibious) → breach + data exfil → secure the archive to a
friendly submarine or subsea pod → destroy the site (demolitions). Each phase
is its own skill roll; failures cascade.

**Torpedoes & naval weapons.** Submarines can purchase torpedoes (heavyweight,
lightweight) and cruise missiles. Used against hostile sea assets (GOI ships,
rival submarines, oil platforms used as enemy sites). Surface combatants carry
anti-ship missiles and CIWS. Engagements resolved as acoustic-duel / BVR
missile exchanges with skill + stealth + ECM rolls.

**Oil platform gameplay hooks.** Beyond being a buildable site, oil platforms
are prime MTF assault targets when rivals hold them — the helipad + sea
approaches make them assault-friendly, and they often house valuable archives
(seawater cooling attracts rival black-site builders).

**Rival GOI site model.** GOIs own sites with the same attributes yours do
(power, cooling, network, archive). Intel from infohazards, SIGINT, and
submarine ISR populates your partial view. Successful MTF raids remove GOI
sites from the map and transfer their archive to you.

None of the above is implemented yet — this section captures design intent so
future phases (12+) can land against a clear vision.

### 24.6 Rival-GOI detection + raids (partial — groundwork landed)

**Groundwork** (implemented):

- Rival GOI catalog: Chaos Insurgency, Marshall Carter & Dark, GOC,
  Prometheus Labs, Church of the Broken God. 13 rival sites seeded on
  first boot across 9 regions.
- Each rival site has a numeric stealth rating (40–80) and a capability
  summary. Sites are unknown to the player by default.
- Intel contact state machine per rival site, per save:
  `unknown` → `rumored` → `located` → `cataloged` (progressive reveal).
- Mission kinds: `sigint`, `elint`, `imint`, `humint`. Base powers 45 /
  50 / 55 / 60; bonuses from:
  - Aircraft `isr_type` matching the mission kind (+20 on match)
  - Vessel equipment (sensor ratings + ELINT suite bonus)
  - Satellites (sigint/imint payloads match)
  - Staff `infosec` skill for HUMINT (scales ≥ 30)
  - Home-site signals gear (`imint-dome`, `comint-mast`, `elint-array`)
- Dispatch semantics: `intel_mission <kind> <region> [asset:id]
  [home:site]`. Scheduler fires `intel_mission_complete` after a
  kind-specific game-time delay; detection roll is
  `1d100 <= clamp(5, 95, power - stealth + 50)` per rival site in
  the region, advancing contact state one step per hit.

**Deferred** (next phase):

- Rival GOIs detecting the player back (symmetric fog-of-war).
- Rival GOI dynamic behavior — they currently sit as static targets.
- Raid pipeline (plan → breach → exfil → destroy) — requires the
  §24.5 combat layer first.
- HUMINT operative pipeline: dedicated staff role, insertion risk,
  burn/extraction mechanics.
- Intel half-life: today contacts never decay. Real intel goes stale.

**Design anchors preserved from the original §24.5/§24.6 sketch:**

Today the IMINT dome, COMINT mast, ELINT array (§13.4) and vessel
sensor gear (§14.0) only raise your own site-security rating — the
defensive half of the loop. The offensive half, planned for the same
phase as §24.5 combat mechanics, closes it:

- **Rival sites as hidden entities** — each GOI owns sites with the same
  attributes you do. Player view is fog-of-war: sites are unknown until
  a sensor detects them.
- **Detection formula** — for each unknown rival site, each of your
  sensor assets rolls against its range / sensitivity / target stealth
  rating (equivalents of `rf-faraday-shielding` and hardened hulls on
  the rival side). Successful rolls surface a rough location, then an
  exact fix, then an infrastructure readout.
- **IMINT** (`imint-dome` + surveillance aircraft + imagery satellites)
  — spots sites above-ground, counts power plants, identifies MobiDCs
  from thermal signature.
- **COMINT** (`comint-mast` + SIGINT satellite + SSN towed array) —
  intercepts rival traffic; yields site inhabitants + scope of ops.
- **ELINT** (`elint-array` + ESM/ELINT suite on subs/ships) —
  fingerprints rival radar/comms emitters; locates the ISR gear they
  use against *you*.
- **Raid pipeline** — once a rival site is fully detected:
  1. Plan — select insertion (airborne, amphibious, underground approach)
  2. Breach — MTF squad rolls against rival security rating
  3. Exfiltrate — their archive contents over secure comms or physical
  4. Destroy — demolition or leave-in-place for persistent intel
- **Risk symmetry** — rival GOIs run the same detection loops against
  you. The same IMINT/COMINT/ELINT gear that lets you see them is what
  the Faraday shielding and counter-UAS systems (§13.4) are designed to
  block. High rating == low detectability.

Ship: land §24.5 combat orders first, then rival-GOI world-model as
hidden entities, then detection rolls, then raid pipeline. Each phase
is independently shippable.

---

## 25. Technical architecture

### 25.1 Layout

```
daemon/
  service.py         systemd/launchd/Windows Service entry
  journal.py         append-only event log, replay on resume
  clock.py           NTP-synced UTC, monotonic progress
  scheduler.py       jobs by ETA timestamp

engine/
  ticks.py           tick loop, event dispatch
  rng.py             seeded PRNG for procedural content
  save.py            SQLite schema, periodic snapshots

resources/
  budget.py          RAM / CPU / storage / bandwidth / funding
  contracts.py       fuel, power, comms, supply agreements

hardware/
  catalog.py         data-driven compute hardware
  gpu.py / npu.py / mainframe.py
  power.py           kW budget, PUE, gensets, solar, fuel contracts
  cooling.py         air / liquid / immersion / seawater / ground-loop
  network.py         latency model, satellite, bandwidth

containment/
  rating.py          numeric containment score
  leak.py            delta-over-time leak model
  vm.py              VM lifecycle, snapshot, encryption state

safety/
  checklists.py      named procedures per action
  guardrails.py      skill-gated enforcement
  mistakes.py        canonical mistake registry + detectors
  exposure.py        infection genesis from mistake
  incident.py        root-cause report generator

facilities/
  site.py            rack / colo / onprem / mobidc / subsea
  vessel.py          hulls, crew, fuel, weather, port calls
  underground.py     excavation, pumps, ventilation, heat rejection
  polar.py           Antarctica logistics, supply windows

fleet/
  hulls.py           sub/ship class catalog, per-hull state
  autonomy.py        N+k redundancy checker, auto-fail-over sim
  damage_control.py  flood/fire/power-fault response
  dry_dock.py        scheduling, exposure-window events
  registration.py    flag-of-convenience, cover identity
  lease.py           lease terms, recall events

subsea/
  acoustics.py       detection risk (own signature × enemy sensors)
  comms_buoy.py      surfacing schedules, contact windows
  depth_profile.py   crush depth, emergency blow

aero/
  aircraft.py        catalog, per-tail state
  uav.py             UAV-specific behavior
  haps.py            solar budget, station-keeping
  airfields.py       infra tiers
  airspace.py        overflight permissions, radar visibility
  flight_ops.py      mission planning, dispatch, diversion
  maintenance.py     A/B/C/D check cycle

orbit/
  buses.py           satellite bus SKUs (CubeSat → Polaris XL)
  payloads.py        modular payload catalog (comms/ISR/compute/storage)
  compose.py         bus + payload composition validator
  orbits.py          orbit tier catalog + coverage/latency rules
  launch.py          vendor catalog, pricing w/ orbit multiplier
  satellites.py      per-sat state, position, passes
  ground.py          station tiers, pass scheduling
  otv.py             OTV-class reusable ops + payload swap
  risk.py            launch + commissioning + on-orbit failure rolls

weapons/
  loadouts.py        passive/active per platform
  escalation.py      consequence tree for firing

threats/
  goi.py             Chaos Insurgency, GOC, MC&D, state intel
  boarding.py        raid mechanics against moving assets

staff/
  roster.py          employees, clearances, certs, burnout
  training.py        curricula w/ real-time durations
  playbooks.py       standing orders
  autonomy.py        decisioning when player absent

aviation_staff/
  pilots.py          ratings, currency, type-ratings
  mechanics.py       A&P, avionics

pager/
  channels/          desktop, email, sms, discord, slack, pushover
  rules.py           severity + schedule + quiet hours

research/
  tree.py            nodes, prereqs, cross-links
  projects.py        lifecycle, milestones, burn
  labs.py            facility tiers, capacity, location bonuses
  scientists.py      PIs, prestige, papers
  risk.py            per-domain failure tables
  leakage.py         defection / raid / publication
  publication.py     publish/classify choice

design/
  bus_std.py         hull/air pallet bus standard versioning
  modules.py         module catalog (research-unlocked)
  slot_map.py        per-hull slot topology + constraints
  composer.py        validated loadout builder
  refit_planner.py   module-swap project planner

market/
  brokers.py         contact network, trust
  listings.py        dynamic hull listings T1–T5
  surveys.py         pre-purchase hull assessment
  negotiation.py     price/terms model

refit/
  yards.py           yard catalog, capacity, relationships
  projects.py        refit milestones, overrun risk
  inspections.py     periodic certifications

missions/
  pallets.py         air mission pallet catalog
  loadouts.py        airframe compat checker

weather/
  ceiling.py         operational minima per airframe
  forecasts.py       scrub / divert decisions

content/
  items.py           procedural infohazard generator
  events.py          event deck, cadence

tui/
  app.py             Textual entry
  attach.py          connect to daemon
  panes/             dashboard, log, incident, pager, command
  pager_view.py      unified inbox
  checklists.py      pre-action checklist widgets
  composer_view.py   module composer (later phase)
```

### 25.2 Persistence

**SQLite** as the save format. Queryable history, good for audit trails, supports the journal + snapshot model.

**Schema pillars:**
- `events` (append-only, UTC-stamped journal)
- `state_snapshots` (periodic; rebuild by replay from nearest snapshot)
- `entities` (sites, hulls, aircraft, staff, items, contracts, projects…)
- `incidents` (permanent browsable inbox)
- `research_nodes` (unlocks)
- `catalogs` (static + research-unlocked module definitions)

### 25.3 Stack

- **Python 3.12+**
- **Textual** (TUI)
- **APScheduler** or custom scheduler for ETA events
- **SQLite** via `sqlite3` or **SQLAlchemy** Core (not ORM bloat)
- **pydantic** for validated entity models
- **watchfiles** / socket server for daemon ↔ TUI IPC
- Optional **NATS** or simple Unix-socket event bus
- Platform service wrappers: `systemd` unit, `launchd` plist, `pywin32` service

Rust / ratatui reserved for a future single-binary rewrite if adoption warrants.

### 25.4 Notifications

- Desktop: `plyer` or platform-native
- Discord / Slack: webhook POST
- Email: SMTP or Mailgun
- SMS: Twilio
- Mobile-convenient: Pushover, ntfy

### 25.5 Visual style

**Textual** with ASCII/unicode box widgets. No imagery. Prioritize dense dashboards (posture sidebar, incident inbox, command pane). Default dark theme.

---

## 26. Phased build plan

### Phase 0 — Daemon skeleton (1–2 weeks)

- systemd / launchd / Windows Service wrappers
- SQLite journal + snapshot
- UTC scheduler
- Attach/detach TUI over Unix socket
- Desktop notifications only
- Smoke test: schedule an event, close TUI, reopen, see it fire

### Phase 1 — MVP shift (3–4 weeks)

- One site, one VM, one tape drive
- Basic compute hardware catalog (3 tiers)
- Scan / acquire / analyze / archive
- Infection state machine + forensic wipe loop
- One skill (`infosec`) with guardrail ramp
- Minimal staff (2–3 analysts) with autonomy rules
- Mistake detection for 6 core mistakes
- Incident report generator
- Discord webhook pager channel
- **Playable loop end-to-end**

### Phase 2 — Fleet / staffing (3–4 weeks)

- Full compute catalog (§10)
- Power + cooling model (§12)
- Networking tiers + contracts (§11, §21)
- Full ops staff lane with training curricula
- Clearance levels + certifications
- Playbooks / standing orders
- Full guardrail ramp across skills
- Expanded mistake taxonomy

### Phase 3 — Logistics (3–4 weeks)

- Ground transport + MobiDC
- Surface ship fleet (T1–T2)
- Field deployment + generators + fuel contracts
- Solar ARM kits
- Aircraft tier (GA + light cargo + helicopter)
- Airfield infrastructure

### Phase 3.5 — Orbit (3–4 weeks)

- Satellite bus catalog (CubeSat through Polaris XL) + payload module catalog
- Launch vendor catalog with orbit-dependent pricing
- Ground station tiers (rented → portable → fixed → deep-space → phased-array)
- Build / integrate / launch pipeline with real-clock lead times
- Orbit-class → mechanical benefits (private satcom, ISR, air-gap storage, compute)
- HAPS / airship interim coverage integration
- OTV-class reusable as plot-gated endgame asset

### Phase 4 — Depth sites & autonomy (4+ weeks)

- Subsea pods (Panthalassa)
- Underground bases
- Antarctica
- Nuclear power tier (micro + SMR)
- Submarine market (T3–T4)
- UUVs / autonomous systems with N+k redundancy
- Mission pallets (air + maritime)

### Phase 5 — Research & modular design (4+ weeks)

- Research tree, labs, scientists
- 4 initial domains, ~20 nodes
- Project lifecycle + risk + publication/classification
- Module composer (v1 — 2–3 hull classes)
- Refit planner

### Phase 6 — Endgame content (ongoing)

- Ibex mainframes + encrypted LPARs
- Typhoon-class acquisition arc
- HAPS fleet + sub-relay
- Full refit-yard relationship model
- Full GOI agent model with fog of war (if chosen, §27)
- Long-horizon campaigns
- Keter / Thaumiel / Apollyon content

**Honest scope note:** phases 0–3 are one-person-achievable over ~4 months at evening/weekend pace. Phases 4+ benefit strongly from collaborators or are long-tail content additions.

---

## 27. Open decisions (final call needed before code)

Numbered for easy response.

| # | Decision | Options | Recommendation |
|---|---|---|---|
| 1 | Single-player vs co-op roadmap | (a) SP only forever (b) SP-first, co-op later (c) co-op from day one | (b) |
| 2 | Cross-device continuity | (a) Local daemon only (b) Hosted tick server in v2 | (a) for v1, reassess |
| 3 | Offline tolerance | (a) Sim pauses when host off (b) Staff AI runs autopilot via playbooks | (b) — "always running" is pillar #2 |
| 4 | Save format | (a) Single JSON blob (b) SQLite | (b) |
| 5 | Seed philosophy | (a) Fully procedural (b) Hand-authored campaign + procedural stream | (b) |
| 6 | Pager channels for v1 | (a) Desktop only (b) Desktop + Discord | (b) |
| 7 | Service install friction | (a) Require background service (b) "Run terminal, leave open" | (a) — fidelity pillar |
| 8 | Bad-luck infection rate | (a) Strictly causal (b) Small bad-luck rate late-game | (a) for v1, (b) v2 |
| 9 | Visual style | Textual with ASCII/unicode box widgets | (confirmed, non-blocking) |
| 10 | Weather/jurisdiction fidelity | (a) Abstract probability (b) Real feeds / UNCLOS-ish | (a) for v1 |
| 11 | Fiber-lay mini-game | (a) 6-phase timer (b) Tactical play during phases | (a) |
| 12 | Nuclear politics | (a) Scripted events (b) Agent-based rival sim | (a) for v1 |
| 13 | Acoustic/detection sim fidelity | (a) Abstract detection prob (b) Full signature-vs-sensor | (a) for v1 |
| 14 | GOI intel (fog both ways) | (a) Player has fog, GOIs omniscient (b) Both have fog | (b) |
| 15 | Hull loss consequences | (a) Run-ender (b) Multi-year setback (c) Recoverable | (b) |
| 16 | Refit yards | (a) Abstract slot pool (b) 3–4 named yards with personalities | (b) |
| 17 | Broker trust | (a) Single numeric stat (b) Full relationship history | (b) |
| 18 | Hull marketplace pacing | (a) Event timer (scarce, "available in Q3") (b) Always-on catalog | (a) |
| 19 | Research secrecy | (a) Full visibility of own projects (b) Fog of progress until milestones | (a) — UX clarity |
| 20 | Technology loss | (a) Techs are permanent once unlocked (b) Can be lost (PI dies, notes corrupted) | (b), rare |
| 21 | Cross-run persistence | (a) Single long save (b) Roguelike seasons w/ meta-progression | (a) |
| 22 | Airspace/radar fidelity | (a) Abstract per-flight detection prob (b) Simulated ADS-B / airspace classes | (a) for v1 |
| 23 | Modular pallet standard unification | (a) Unified sub + air research track (b) Separate domains | (a) — elegant |
| 24 | Autonomous kinetic capability | (a) Weaponized autonomous allowed (b) Kinetic crewed-only | (b) — narrative weight |
| 25 | Branding: keep "Typhoon" | (a) Keep (NATO public designation) (b) Rename (Tempest-class) | (a) per user |
| 26 | Apollyon-class content | (a) Excluded (b) Included as story gate | (b) |
| 27 | Ethical actions UI (mnestic on own staff, area dispersal) | (a) Silent mechanic (b) Explicit "ethics flag" prompts | (b) |
| 28 | Orbital pass modeling | (a) Abstract per-sat "contact windows/day" stat (b) True orbital propagation via SGP4-lite | (a) for v1 |
| 29 | Satellite pricing realism | (a) Snapshot 2026 pricing baked in (b) Dynamic market with vendor-slot availability | (b) — matches broker/market patterns for hulls |
| 30 | OTV gating | (a) Plot-event unlock only (b) Extreme-cost late-game purchasable | (a) — narrative weight |
| 31 | Ground station foreign-SIGINT risk | (a) Binary (compromised or not) (b) Continuous leak probability per pass | (b) v2; (a) v1 |

---

## 28. Out-of-scope / deferred

Explicitly *not* in the design:

- **Graphical client** — TUI only. Future rewrite possibility.
- **Multiplayer / shared save** — single-player only.
- **Real web crawling** — "scans" are simulated; no network activity on behalf of the game.
- **Live SCP wiki content ingestion** — use procedural generator in the spirit of canon under CC BY-SA only if campaign content is hand-authored.
- **VR / AR** — no.
- **Mobile native app** — Pushover / ntfy covers mobile notifications; no native UI.
- **Streaming integrations** — no Twitch/OBS hooks planned.
- **Real-world weather API** — stylized weather only (unless decision #10 flips).
- **Real-world market data feeds** — stylized economy.

---

## Appendix A — Trademark & naming

All real-world brand names renamed for the project. Real analogs noted only in this design doc for the author's reference; the shipped game never uses them. Exceptions:

- **Typhoon-class** — NATO reporting designation, public vocabulary; preserved per user direction.
- **Delta / Oscar / Foxtrot / Romeo / Victor / Akula / Sturgeon / Virginia / Astute / Suffren / Yasen / Borei** — NATO reporting designations; treated as public vocabulary if used, otherwise renamed.
- **Panthalassa** — named as the in-world subsea company (real company's name in our universe). If legal review flags, rename to **Thalassa Systems**.
- **SCP / Foundation fiction** — used under CC BY-SA 3.0 compliance; all original anomalous item content procedural or original-authored; no direct lifting of wiki-specific items.

---

## Appendix B — Glossary

- **MobiDC** — containerized modular data center (20 or 40 ft ISO)
- **LPAR** — logical partition on a mainframe; each has encrypted memory
- **SEV** — hardware memory encryption analog (AMD SEV-like)
- **Kant counter** — canonical SCP device for detecting reality-defiance (used as lore device for anomaly detection)
- **Mnestic / amnestic** — memory-enhancement / memory-erasure drugs (SCP canon)
- **GOI** — Group of Interest (rival/adjacent organization)
- **O5** — in-fiction Foundation leadership (funding authority in-game)
- **PI** — Principal Investigator (research lead)
- **HAPS** — High-Altitude Pseudo-Satellite (stratospheric UAV / balloon)
- **UUV / XLUUV** — Unmanned Underwater Vehicle / Extra-Large variant
- **SSK / SSN / SSBN / SSGN** — diesel-electric / nuclear attack / ballistic-missile nuclear / cruise-missile nuclear submarine
- **AIP** — Air-Independent Propulsion
- **PUE** — Power Usage Effectiveness (DC efficiency metric)
- **FBO** — Fixed-Base Operator (private-aviation service provider)
- **ADS-B** — aircraft position broadcast; public via enthusiast trackers
- **A/B/C/D check** — aviation maintenance cycle levels
- **SOSUS / A2/AD** — undersea surveillance / anti-access-area-denial zones
- **QKD** — Quantum Key Distribution
- **OTEC** — Ocean Thermal Energy Conversion
- **RTG** — Radioisotope Thermoelectric Generator
- **SMR** — Small Modular Reactor
- **CI** — Counterintelligence
- **PMSC** — Private Military / Security Contractor
- **LEO / MEO / GEO / HEO / SSO** — Low / Medium / Geostationary / Highly-Elliptical / Sun-Synchronous orbit
- **GTO** — Geostationary Transfer Orbit
- **CubeSat** — standardized small-satellite form factor (1U = 10×10×10 cm); open standard from Cal Poly
- **ESPA** — Evolved Expendable Launch Vehicle Secondary Payload Adapter (rideshare class)
- **SIGINT / ELINT / IMINT** — Signals / Electronic / Imagery intelligence
- **SAR** — Synthetic Aperture Radar (all-weather imagery)
- **EO** — Electro-Optical (visible-light imaging)
- **OTV** — Orbital Test Vehicle (X-37-class reusable)
- **ASAT** — Anti-Satellite weapon
- **HSM** — Hardware Security Module (key storage)
