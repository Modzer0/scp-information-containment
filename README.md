# SCP: Information Containment

A terminal-based **real-clock** information-containment operations simulator.
You run a Foundation-adjacent org: acquire suspected infohazards, analyze them
in containment-rated VMs, archive them for funding, and keep the lights on.
The simulation ticks against wall-clock UTC — no pause, no speed-up. Your org
keeps running while the TUI is closed; a background daemon holds the state.

See [DESIGN.md](DESIGN.md) for the full design document (1,600+ lines covering
hardware, logistics, staff, orbit, subs, facilities, research, risk).

---

## Quick start

Requires **Python 3.11+** (tested on 3.14 Windows). Clone and install:

```bash
git clone <this-repo-url>
cd SCP

python -m venv .venv
. .venv/Scripts/activate          # Windows (bash)
# or: . .venv/bin/activate        # macOS/Linux
# or: .venv\Scripts\Activate.ps1  # Windows PowerShell

pip install -e .
```

Run in two terminals:

```bash
# Terminal 1 — start the daemon (long-running background service)
python -m scp daemon

# Terminal 2 — attach the TUI
python -m scp tui
```

All state persists at `~/.scp/scp.db`. Stopping the TUI does not stop the
daemon; your site keeps running. To stop the daemon from the TUI: `shutdown --confirm`.

## Your first shift

Inside the TUI, type `help` for topic-organized commands, or follow this script:

```text
sitrep                                  # dashboard: funding, staff, sites
scan                                    # start a 30s scan for candidate items
# wait a bit (events appear live with ● symbols)
items candidate                         # see what turned up
acquire 1                               # move item 1 to quarantine
analyze 1 1                             # analyze item 1 on vm 1
# wait — analysis fires at ETA with severity color-coded
archive 1                               # if stable: archive for funding reward
```

If `analyze` is refused with a soft-rail warning, re-issue with `override`
at the end. If a host gets infected, use `wipe <host_id>` to restore it.

## Key commands

| Command | What it does |
|---|---|
| `sitrep` | Full dashboard — funding, sites, fleets, alerts |
| `next` | Next 10 scheduled events with relative ETAs |
| `recent` | Recent journal entries |
| `help [topic]` | List topics, or show commands in one |
| `scan` · `acquire` · `analyze` · `archive` · `wipe` | Core operations |
| `catalog [category]` | Browse hardware (68 SKUs across 14 categories) |
| `buy <sku> [target]` | Order hardware; install-complete fires at ETA |
| `site_types` · `establish_site <type> <name>` | Spin up new sites |
| `networks` · `upgrade_network <site> <tier>` | Change site connectivity |
| `courses` · `enroll <staff> <course>` | Staff training |
| `subscribe <type> <target>` · `contracts` | Recurring billing (fuel, scanner feeds) |
| `playbook <site> <rule> on\|off` | Autonomy rules for when you're away |
| `incidents` · `incident <id>` | Browse incident reports |
| `aircraft` · `ships` · `submarines` · `satellites` | Fleet rosters |
| `transfer_item <item> <site> [method]` | Ship archived items between sites |
| `outages` · `trigger_outage <site>` | Civilian grid-outage state |
| `shutdown --confirm` | Stop the daemon gracefully |

Type `quit` to exit the TUI (daemon keeps running).

## Optional configuration

| Environment variable | Effect |
|---|---|
| `SCP_TIME_SCALE` | Action-duration multiplier. Default `1.0`. Set `0.1` for 10× faster dev play, `10.0` for realistic long timelines. |
| `SCP_DISCORD_WEBHOOK` | Post alert-severity events to a Discord channel |
| `SCP_DISCORD_MIN_SEV` | Minimum severity to post: `INFO` / `NOTICE` / `WARNING` / `ALERT` / `BREACH` (default `ALERT`) |

## Features at a glance

**Core loop**
- Real-clock UTC simulation; scheduler persists to SQLite and rehydrates on restart
- Procedural infohazard generator — Safe / Euclid / Keter classes with hazard strength, memetic load, form, effect
- Numeric containment rating per VM (memory encryption + isolation + mnestic firmware + shielding + scanner freshness)
- Delta-driven leak model: stable → slow_leak → active_leak → catastrophic
- Operator skills with guardrail ramp (hard / soft / warn / expert)
- 10 mistake detectors — undersized containment, tainted VM, stale scanner, insufficient clearance, power/cooling overload, unencrypted commercial link, etc.
- Auto-generated incident reports with root cause, contributing factors, recommendations
- Brownout mid-analysis: overloaded sites roll leak-tier promotion

**Infrastructure (68 SKUs, 14 categories)**
- Compute: servers, AI pods (Invidia DGZ), mainframes (Ibex Z-class LPARs)
- Encryption: software VPN → hardware → Type-1 (gates commercial-link work)
- Networking: dial-up → dark fiber → Starstream → GEO sat → owned `private_sat`
- Power: gensets (20/100/500 kW), solar, kilopower μ-reactor, eVinci SMR, NuScale SMR, **Gen-IV molten-salt MSRs** (passive safety)
- Resilience: UPS → 1 MWh LFP banks; fuel tanks (24h → 30 days)
- Facilities: office closet, on-prem DC, MobiDC container, field site, subsea pod, underground bunker, Antarctica
- Sites ship with initial resilience; expansion requires proportional battery + fuel

**Fleets**
- Aircraft (19 types): GA, biz jets, C-130/C-17/C-5 class cargo, AWACS, SIGINT (P-8, RC-135), JSTARS, U-2, SR-71, F-22/F-35/F-47 stealth, helicopters, amphibians
- Ships: yachts, OSVs, research vessels, converted icebreakers
- Submarines (9 types): UUVs, XLUUVs, diesel-electric exports (Type 209/214, Scorpene, Kilo surplus, Foxtrot, Victor SSN), Typhoon conversion
- Satellites: CubeSat/Smallsat/Largesat buses, 5 payload types (comms/storage/compute/sigint/imint), OTV reusable
- Owned-asset transport discounts (halved air / sea cost)

**Logistics**
- 4 transport methods: truck / air / rail / sea with real-clock transit times
- Inter-site moves for items, hosts, staff
- Airfield + port + ground-station infrastructure gates ownership
- Stealth + ISR chained gates (SR-71 needs 2 prior ISR; F-47 needs 2 prior stealth)

**Civilian-outage simulation**
- Daily per-site roll for grid outages (~2% probability, 1–12h duration)
- Ride-through calc: `battery_kwh / load_kw + fuel_hours`
- Sites with adequate resilience stay up silently; undersized sites go dark

**Operations + autonomy**
- Staff: player + 2 NPCs at bootstrap; XP per action with diminishing returns
- Training: 6 courses with real-clock durations + prereq chains
- Contracts: recurring billing for scanner feeds, diesel, Jet-A, bunker fuel
- Playbooks: per-site auto-rules so the sim keeps working while you sleep

**TUI**
- Textual with unicode widgets — clock, status bar, scrollable log, command input
- Live event stream over a second socket (push events appear as `●` rows)
- Status bar: funding, pending, contracts, outages, alerts — refreshes on event + 3s tick
- Topic-organized `help` (9 topics, 48 commands)
- Humanized time + money (`in 2h 14m`, `$1.05M`)
- Detail views: `item <id>`, `vm <id>` (containment component bars), `host <id>`
- Typo suggestions + auto-reconnect on daemon drop
- Optional Discord webhook for alerts

## Project layout

```
scp/
  __main__.py                # entry dispatcher
  daemon/                    # long-running simulation
    clock.py                 # UTC, NTP-synced via system clock
    journal.py               # SQLite schema + entity CRUD + event log
    scheduler.py             # heap + SQLite-backed scheduler
    ipc.py                   # JSON-lines TCP server
    notifications.py         # plyer desktop toasts
    main.py                  # daemon entry + dispatch
    containment.py           # VmSpec + leak_category
    mistakes.py              # mistake detector registry
    guardrail.py             # skill-gated rail decisions
    incidents.py             # incident report generator
    gameplay.py              # bootstrap + action loop
    procurement.py           # buy + install + site utilization
    training.py              # course catalog
    network.py               # connectivity tiers
    contracts.py             # recurring billing framework
    playbooks.py             # autonomy rules
    sites.py                 # site type catalog
    transport.py             # ground/air/sea/rail + host + staff moves
    outages.py               # civilian-grid outage simulation
    content/items.py         # procedural infohazard generator
    hardware/catalog.py      # 68 SKUs across 14 categories
    pager/discord.py         # optional webhook pager
  tui/
    client.py                # async request/reply socket client
    events.py                # subscription client (push events)
    format.py                # humanize_eta / humanize_money
    main.py                  # Textual app + help + detail views

tests/
  phase4_e2e.py              # regression: payloads, OTV, sites, subs, contracts
  phase5_e2e.py              # regression: aircraft, stealth gates, shutdown
  phase5b_e2e.py             # regression: batteries, fuel, outages

DESIGN.md                    # full design document
```

## Running tests

```bash
# Compressed time makes long-clock actions finish in seconds
SCP_TIME_SCALE=0.00005 python tests/phase4_e2e.py
SCP_TIME_SCALE=0.00005 python tests/phase5_e2e.py
SCP_TIME_SCALE=0.00005 python tests/phase5b_e2e.py
```

All three suites must pass together. They exercise procurement, gating,
lapse effects, shutdown, resilience, and outage simulation against a fresh
temporary SQLite database.

## Resetting state

State lives at `~/.scp/scp.db`. Stop the daemon (`shutdown --confirm`),
delete the file, and relaunch for a fresh campaign. Schema additions
between runs are applied via `ALTER TABLE ADD COLUMN` where possible, so
existing DBs usually keep working.

## Status

Active development. The daemon, scheduler, journal, and full TUI are
production-quality; gameplay systems land incrementally. See the phase log
in `DESIGN.md` §26 for roadmap and deferred items.

## License

TBD — see LICENSE file when present.
