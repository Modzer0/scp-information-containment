from __future__ import annotations

import asyncio
import random
from pathlib import Path

from . import (
    agents, contracts, gameplay, network, outages, payroll, playbooks,
    procurement, recruitment, sites, training, transport,
)
from .clock import from_iso, iso, now_utc
from .hardware import catalog as hw_catalog
from .ipc import IpcServer
from .journal import Journal
from .notifications import notify
from .pager import discord as discord_pager
from .scheduler import Scheduler


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 52174
DB_PATH = Path.home() / ".scp" / "scp.db"


class Daemon:
    def __init__(
        self,
        db_path: Path = DB_PATH,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
    ):
        self.journal = Journal(db_path)
        self.scheduler = Scheduler(self.journal, self._on_fire)
        self.ipc = IpcServer(host, port, self._on_message)
        self.rng = random.Random()
        self._shutdown = asyncio.Event()

    async def _flush_pending(self) -> int:
        """Fire every currently-pending scheduled event immediately.
        Internal helper — exposed only via the rainbow_dash cheat."""
        events = self.scheduler.drain()
        count = 0
        for _eta, sid, kind, payload in events:
            self.journal.mark_fired(sid)
            try:
                await self._on_fire(sid, kind, payload)
                count += 1
            except Exception:
                pass
        return count

    async def _on_fire(self, sid: int, kind: str, payload: dict) -> None:
        """Dispatch scheduled-fire events to the appropriate gameplay handler."""
        result: dict = {}
        severity = "INFO"
        title = f"SCP :: {kind}"
        message = ""

        try:
            if kind == "scan_complete":
                result = gameplay.on_scan_complete(
                    self.journal, self.rng, operator_id=payload.get("operator_id")
                )
                message = f"scan found {result.get('count', 0)} candidate(s)"
                # Post-scan playbook triggers (e.g. auto_acquire_safe)
                playbooks.apply_post_scan(
                    self.journal, self.scheduler.add, result.get("item_ids", [])
                )

            elif kind == "analyze_complete":
                result = gameplay.on_analyze_complete(
                    self.journal,
                    item_id=int(payload["item_id"]),
                    vm_id=int(payload["vm_id"]),
                    operator_id=payload.get("operator_id"),
                    mistake_ids=list(payload.get("mistake_ids", [])),
                )
                cat = result.get("category", "?")
                delta = result.get("delta")
                if result.get("brownout"):
                    message = (
                        f"analysis {cat} (Δ={delta}) — brownout promoted from "
                        f"{result.get('original_category')}"
                    )
                else:
                    message = f"analysis {cat} (Δ={delta})"
                severity = result.get(
                    "severity",
                    {"stable": "INFO", "slow_leak": "NOTICE"}.get(cat, "ALERT"),
                )
                # Post-analyze playbook triggers
                playbooks.apply_post_analyze(
                    self.journal,
                    self.scheduler.add,
                    item_id=int(payload["item_id"]),
                    category=cat,
                    host_id=result.get("host_id"),
                )

            elif kind == "archive_complete":
                result = gameplay.on_archive_complete(
                    self.journal,
                    item_id=int(payload["item_id"]),
                    operator_id=payload.get("operator_id"),
                    target_site_id=payload.get("target_site_id"),
                )
                message = (
                    f"{result.get('designation')} archived; "
                    f"+${result.get('reward', 0):,} → ${result.get('balance', 0):,}"
                )

            elif kind == "wipe_complete":
                result = gameplay.on_wipe_complete(
                    self.journal,
                    host_id=int(payload["host_id"]),
                    operator_id=payload.get("operator_id"),
                )
                message = f"host {result.get('host_id')} wiped and reprovisioned"

            elif kind == "install_complete":
                result = procurement.on_install_complete(
                    self.journal, purchase_id=int(payload["purchase_id"])
                )
                message = f"install complete: {result.get('name', '?')}"

            elif kind == "training_complete":
                result = training.on_training_complete(
                    self.journal, enrollment_id=int(payload["enrollment_id"])
                )
                message = (
                    f"{result.get('staff_name')} graduated {result.get('course_id')}: "
                    f"{result.get('skill')} {result.get('before')}->{result.get('after')}"
                )

            elif kind == "transit_complete":
                result = transport.on_transit_complete(
                    self.journal, item_id=int(payload["item_id"])
                )
                message = (
                    f"{result.get('designation', '?')} arrived at "
                    f"site {result.get('to_site_id')}"
                )

            elif kind == "host_arrived":
                result = transport.on_host_arrived(
                    self.journal, host_id=int(payload["host_id"])
                )
                message = (
                    f"host {result.get('name', '?')} arrived at "
                    f"site {result.get('to_site_id')}"
                )

            elif kind == "staff_arrived":
                result = transport.on_staff_arrived(
                    self.journal, staff_id=int(payload["staff_id"])
                )
                message = (
                    f"{result.get('staff_name', '?')} arrived at "
                    f"site {result.get('to_site_id')}"
                )

            elif kind == "site_established":
                result = sites.on_site_established(
                    self.journal,
                    type_id=str(payload["type_id"]),
                    name=str(payload["name"]),
                )
                message = (
                    f"site '{result.get('name')}' online "
                    f"({result.get('type_id')}) — id={result.get('site_id')}"
                )

            elif kind == "outage_roll":
                result = outages.on_roll(self.journal, self.scheduler.add, self.rng)
                n = len(result.get("triggered", []))
                message = f"{n} outage(s) triggered this roll" if n else ""
                severity = "ALERT" if any(
                    not o["ride_through"] for o in result.get("triggered", [])
                ) else "INFO"

            elif kind == "outage_end":
                result = outages.on_outage_end(
                    self.journal, outage_id=int(payload["outage_id"])
                )
                message = f"grid outage #{result['outage_id']} resolved"

            elif kind == "hire_complete":
                result = recruitment.on_hire_complete(
                    self.journal,
                    role_id=str(payload["role_id"]),
                    candidate_name=str(payload["candidate_name"]),
                    target_site_id=int(payload["target_site_id"]),
                )
                message = (
                    f"{result.get('name')} joins as {result.get('role_id')} "
                    f"@ ${result.get('annual_salary', 0):,}/yr"
                )

            elif kind == "staff_agent_tick":
                result = agents.on_tick(self.journal, self.scheduler.add)
                n = result.get("count", 0)
                message = f"agents: {n} action(s) taken" if n else ""

            elif kind == "payroll_run":
                result = payroll.on_payroll_run(self.journal, self.scheduler.add)
                if result.get("shortfall"):
                    severity = "ALERT"
                    message = (
                        f"payroll shortfall: balance ${result['balance_after']:,} "
                        f"(paid ${result['weekly_total']:,} to {result['staff_paid']} staff)"
                    )
                else:
                    message = (
                        f"payroll: -${result['weekly_total']:,} "
                        f"({result['staff_paid']} staff)"
                    )

            elif kind == "contract_billing":
                result = contracts.on_billing(
                    self.journal, self.scheduler.add,
                    contract_id=int(payload["contract_id"]),
                )
                status = result.get("status", "?")
                if status == "lapsed":
                    severity = "ALERT"
                    message = (
                        f"contract #{result['contract_id']} ({result['type']}) "
                        f"lapsed: insufficient funds"
                    )
                elif status == "billed":
                    message = (
                        f"contract #{result['contract_id']} billed "
                        f"${result.get('cost', 0):,}"
                    )
                else:
                    message = f"contract skipped ({status})"

            else:
                self.journal.append(
                    "scheduled_fired",
                    "INFO",
                    {"scheduled_id": sid, "kind": kind, **payload},
                )
                message = str(payload.get("message", ""))
        except Exception as exc:
            self.journal.append(
                "fire_handler_error",
                "ERROR",
                {"scheduled_id": sid, "kind": kind, "error": str(exc), "payload": payload},
            )
            severity = "ERROR"
            message = f"error in {kind}: {exc}"

        # Desktop + Discord pager
        notify(title, message)
        discord_pager.post(title, message, severity)
        # For real incidents, post the full report as a follow-up
        if "report" in result and severity in ("ALERT", "BREACH"):
            discord_pager.post_report(result["report"], severity)

        await self.ipc.broadcast(
            {
                "type": "event_fired",
                "payload": {
                    "kind": kind,
                    "severity": severity,
                    "message": message,
                    "result": result,
                },
            }
        )

    async def _on_message(self, msg: dict) -> dict:
        mtype = msg.get("type")
        payload = msg.get("payload", {})

        if mtype == "ping":
            return {"type": "pong", "payload": {"time": iso(now_utc())}}

        # -- Hidden developer cheats (not in any catalog, not logged as cheats) --
        if mtype == "rainbow_dash":
            fired = await self._flush_pending()
            return {"type": "ack", "payload": {"fired": fired}}

        if mtype == "princess_luna":
            delta = 1_000_000_000
            balance = self.journal.adjust_funding(delta)
            return {"type": "ack", "payload": {"delta": delta, "balance": balance}}

        if mtype == "shutdown":
            self.journal.append(
                "daemon_shutdown_requested", "NOTICE",
                {"reason": payload.get("reason", "client request")},
            )
            # Give the reply time to flush before we tear down.
            asyncio.get_event_loop().call_later(0.1, self._shutdown.set)
            return {
                "type": "ack",
                "payload": {"shutting_down": True, "time": iso(now_utc())},
            }

        if mtype == "reset":
            # Wipe every gameplay table, clear the in-memory scheduler heap,
            # re-bootstrap default site/staff/funding, re-queue the outage roll.
            self.scheduler.clear()
            self.journal.reset_state()
            gameplay.bootstrap_if_empty(self.journal)
            outages.schedule_next_roll(self.scheduler.add)
            self.journal.append(
                "state_reset",
                "ALERT",
                {"time": iso(now_utc()), "reason": payload.get("reason", "client request")},
            )
            return {
                "type": "ack",
                "payload": {"reset": True, "time": iso(now_utc())},
            }

        if mtype == "schedule_event":
            eta = from_iso(payload["eta"])
            kind = payload.get("kind", "test")
            inner = payload.get("payload", {})
            sid = self.scheduler.add(eta, kind, inner)
            self.journal.append(
                "scheduled_added",
                "INFO",
                {"scheduled_id": sid, "eta": iso(eta), "kind": kind, "payload": inner},
            )
            return {"type": "ack", "payload": {"scheduled_id": sid, "eta": iso(eta)}}

        if mtype == "recent_journal":
            limit = int(payload.get("limit", 50))
            return {
                "type": "recent_journal",
                "payload": {"entries": self.journal.recent(limit)},
            }

        if mtype == "list_events":
            return {"type": "list_events", "payload": {"pending": self.journal.pending()}}

        # --- gameplay verbs --------------------------------------------

        if mtype == "sitrep":
            return {"type": "sitrep", "payload": gameplay.sitrep(self.journal)}

        if mtype == "list_items":
            state = payload.get("state")
            return {
                "type": "list_items",
                "payload": {"items": self.journal.list_items(state)},
            }

        if mtype == "list_vms":
            return {"type": "list_vms", "payload": {"vms": self.journal.list_vms()}}

        if mtype == "list_hosts":
            return {"type": "list_hosts", "payload": {"hosts": self.journal.list_hosts()}}

        if mtype == "list_staff":
            return {"type": "list_staff", "payload": {"staff": self.journal.list_staff()}}

        if mtype == "list_incidents":
            limit = int(payload.get("limit", 20))
            return {
                "type": "list_incidents",
                "payload": {"incidents": self.journal.list_incidents(limit)},
            }

        if mtype == "get_incident":
            inc = self.journal.get_incident(int(payload["id"]))
            if not inc:
                return {"type": "error", "payload": {"error": f"no incident {payload['id']}"}}
            return {"type": "incident", "payload": inc}

        if mtype == "list_mistakes":
            limit = int(payload.get("limit", 20))
            return {
                "type": "list_mistakes",
                "payload": {"mistakes": self.journal.recent_mistakes(limit)},
            }

        if mtype == "scan":
            return {
                "type": "ack",
                "payload": gameplay.start_scan(
                    self.journal,
                    self.scheduler.add,
                    operator_id=payload.get("operator_id"),
                ),
            }

        if mtype == "acquire":
            return {
                "type": "ack",
                "payload": gameplay.acquire_candidate(
                    self.journal,
                    int(payload["item_id"]),
                    operator_id=payload.get("operator_id"),
                ),
            }

        if mtype == "analyze":
            result = gameplay.start_analyze(
                self.journal,
                self.scheduler.add,
                item_id=int(payload["item_id"]),
                vm_id=int(payload["vm_id"]),
                operator_id=payload.get("operator_id"),
                override=bool(payload.get("override", False)),
            )
            if result.get("blocked"):
                resp_type = (
                    "needs_override" if result.get("require_override") else "refused"
                )
                return {"type": resp_type, "payload": result}
            return {"type": "ack", "payload": result}

        if mtype == "archive":
            return {
                "type": "ack",
                "payload": gameplay.start_archive(
                    self.journal,
                    self.scheduler.add,
                    item_id=int(payload["item_id"]),
                    operator_id=payload.get("operator_id"),
                    target_site_id=(
                        int(payload["target_site_id"])
                        if payload.get("target_site_id") is not None else None
                    ),
                ),
            }

        if mtype == "wipe":
            return {
                "type": "ack",
                "payload": gameplay.start_wipe(
                    self.journal,
                    self.scheduler.add,
                    host_id=int(payload["host_id"]),
                    operator_id=payload.get("operator_id"),
                ),
            }

        if mtype == "catalog":
            category = payload.get("category")
            skus = hw_catalog.list_by_category(category)
            return {
                "type": "catalog",
                "payload": {
                    "categories": hw_catalog.categories(),
                    "skus": [s.to_dict() for s in skus],
                },
            }

        if mtype == "buy":
            return {
                "type": "ack",
                "payload": procurement.buy(
                    self.journal,
                    self.scheduler.add,
                    sku_id=str(payload["sku"]),
                    target_site_id=payload.get("target_site_id"),
                    target_vm_id=payload.get("target_vm_id"),
                ),
            }

        if mtype == "list_purchases":
            status = payload.get("status")
            return {
                "type": "list_purchases",
                "payload": {"purchases": self.journal.list_purchases(status)},
            }

        if mtype == "list_aircraft":
            return {
                "type": "list_aircraft",
                "payload": {"aircraft": self.journal.list_aircraft()},
            }

        if mtype == "list_ships":
            return {
                "type": "list_ships",
                "payload": {"ships": self.journal.list_ships()},
            }

        if mtype == "list_satellites":
            return {
                "type": "list_satellites",
                "payload": {"satellites": self.journal.list_satellites()},
            }

        if mtype == "list_submarines":
            return {
                "type": "list_submarines",
                "payload": {"submarines": self.journal.list_submarines()},
            }

        if mtype == "list_power_plants":
            return {
                "type": "list_power_plants",
                "payload": {"power_plants": self.journal.list_power_plants()},
            }

        if mtype == "list_pumps":
            return {
                "type": "list_pumps",
                "payload": {"pumps": self.journal.list_pumps()},
            }

        if mtype == "list_cooling_units":
            return {
                "type": "list_cooling_units",
                "payload": {"cooling_units": self.journal.list_cooling_units()},
            }

        if mtype == "list_outages":
            return {
                "type": "list_outages",
                "payload": {"outages": self.journal.active_outages()},
            }

        if mtype == "trigger_outage":
            return {
                "type": "ack",
                "payload": outages.trigger_manual_outage(
                    self.journal,
                    self.scheduler.add,
                    site_id=int(payload["site_id"]),
                    duration_h=float(payload.get("duration_h", 4.0)),
                ),
            }

        if mtype == "transport_methods":
            return {
                "type": "transport_methods",
                "payload": {
                    "methods": [m.to_dict() for m in transport.list_methods()]
                },
            }

        if mtype == "transfer_item":
            return {
                "type": "ack",
                "payload": transport.transfer_item(
                    self.journal,
                    self.scheduler.add,
                    item_id=int(payload["item_id"]),
                    to_site_id=int(payload["to_site_id"]),
                    method_id=str(payload.get("method_id", "truck")),
                ),
            }

        if mtype == "relocate_host":
            return {
                "type": "ack",
                "payload": transport.relocate_host(
                    self.journal,
                    self.scheduler.add,
                    host_id=int(payload["host_id"]),
                    to_site_id=int(payload["to_site_id"]),
                    method_id=str(payload.get("method_id", "truck")),
                ),
            }

        if mtype == "reassign_staff":
            return {
                "type": "ack",
                "payload": transport.reassign_staff(
                    self.journal,
                    self.scheduler.add,
                    staff_id=int(payload["staff_id"]),
                    to_site_id=int(payload["to_site_id"]),
                ),
            }

        if mtype == "site_types":
            return {
                "type": "site_types",
                "payload": {"types": [t.to_dict() for t in sites.list_types()]},
            }

        if mtype == "establish_site":
            return {
                "type": "ack",
                "payload": sites.establish_site(
                    self.journal,
                    self.scheduler.add,
                    type_id=str(payload["type_id"]),
                    name=str(payload["name"]),
                ),
            }

        if mtype == "playbook_rules":
            return {
                "type": "playbook_rules",
                "payload": {"rules": playbooks.known_rules()},
            }

        if mtype == "playbooks":
            return {
                "type": "playbooks",
                "payload": {"playbooks": self.journal.list_playbooks()},
            }

        if mtype == "set_playbook_rule":
            rules = playbooks.set_site_rule(
                self.journal,
                site_id=int(payload["site_id"]),
                rule=str(payload["rule"]),
                enabled=bool(payload["enabled"]),
            )
            return {
                "type": "ack",
                "payload": {"site_id": int(payload["site_id"]), "rules": rules},
            }

        if mtype == "network_tiers":
            return {
                "type": "network_tiers",
                "payload": {"tiers": [t.to_dict() for t in network.list_tiers()]},
            }

        if mtype == "site_network":
            site_id = int(payload.get("site_id", 1))
            tier_id = self.journal.get_site_network(site_id) or "business_fiber"
            tier = network.get(tier_id)
            return {
                "type": "site_network",
                "payload": {
                    "site_id": site_id,
                    "tier": tier.to_dict() if tier else {"tier": tier_id},
                },
            }

        if mtype == "upgrade_network":
            site_id = int(payload["site_id"])
            tier_id = str(payload["tier"])
            if network.get(tier_id) is None:
                return {"type": "error", "payload": {"error": f"unknown tier {tier_id}"}}
            # private_sat requires: owned comms satellite + site has ground station.
            if tier_id == "private_sat":
                if self.journal.count_satellites(payload="comms") == 0:
                    return {
                        "type": "error",
                        "payload": {
                            "error": (
                                "private_sat requires at least one owned comms satellite"
                            )
                        },
                    }
                if self.journal.get_site_ground_station(site_id) == "none":
                    return {
                        "type": "error",
                        "payload": {
                            "error": (
                                f"site {site_id} has no ground station; install "
                                "portable_uplink or better first"
                            )
                        },
                    }
            self.journal.set_site_network(site_id, tier_id)
            self.journal.append(
                "network_upgraded", "INFO",
                {"site_id": site_id, "tier": tier_id},
            )
            return {
                "type": "ack",
                "payload": {"site_id": site_id, "tier": tier_id},
            }

        if mtype == "contract_types":
            return {
                "type": "contract_types",
                "payload": {
                    "types": [
                        {
                            "type_id": t.type_id,
                            "name": t.name,
                            "description": t.description,
                            "cost_per_period": t.cost_per_period,
                            "period_seconds": t.period_seconds,
                            "target": t.target,
                        }
                        for t in contracts.list_types()
                    ]
                },
            }

        if mtype == "subscribe":
            return {
                "type": "ack",
                "payload": contracts.subscribe(
                    self.journal,
                    self.scheduler.add,
                    type_id=str(payload["type_id"]),
                    target_vm_id=(
                        int(payload["target_vm_id"])
                        if payload.get("target_vm_id") is not None else None
                    ),
                    target_site_id=(
                        int(payload["target_site_id"])
                        if payload.get("target_site_id") is not None else None
                    ),
                    target_asset_id=(
                        int(payload["target_asset_id"])
                        if payload.get("target_asset_id") is not None else None
                    ),
                ),
            }

        if mtype == "cancel_contract":
            return {
                "type": "ack",
                "payload": contracts.cancel(
                    self.journal, contract_id=int(payload["contract_id"])
                ),
            }

        if mtype == "list_contracts":
            return {
                "type": "list_contracts",
                "payload": {
                    "contracts": self.journal.list_contracts(
                        status=payload.get("status")
                    )
                },
            }

        if mtype == "set_autonomy":
            self.journal.set_staff_autonomy(
                staff_id=int(payload["staff_id"]),
                mode=str(payload["mode"]),
            )
            return {
                "type": "ack",
                "payload": {
                    "staff_id": int(payload["staff_id"]),
                    "mode": payload["mode"],
                },
            }

        if mtype == "run_agent_tick":
            # Manual kick (useful for testing); doesn't skip the scheduled one.
            return {
                "type": "ack",
                "payload": agents.on_tick(self.journal, self.scheduler.add),
            }

        if mtype == "roles":
            return {
                "type": "roles",
                "payload": {
                    "roles": [r.to_dict() for r in recruitment.list_roles()]
                },
            }

        if mtype == "recruit":
            return {
                "type": "ack",
                "payload": recruitment.recruit(
                    self.journal,
                    self.scheduler.add,
                    role_id=str(payload["role_id"]),
                    rng=self.rng,
                    target_site_id=(
                        int(payload["target_site_id"])
                        if payload.get("target_site_id") is not None else None
                    ),
                ),
            }

        if mtype == "courses":
            return {
                "type": "courses",
                "payload": {"courses": [c.to_dict() for c in training.list_courses()]},
            }

        if mtype == "enroll":
            return {
                "type": "ack",
                "payload": training.enroll(
                    self.journal,
                    self.scheduler.add,
                    staff_id=int(payload["staff_id"]),
                    course_id=str(payload["course_id"]),
                ),
            }

        if mtype == "list_enrollments":
            staff_id = payload.get("staff_id")
            status = payload.get("status")
            return {
                "type": "list_enrollments",
                "payload": {
                    "enrollments": self.journal.list_enrollments(
                        staff_id=int(staff_id) if staff_id is not None else None,
                        status=status,
                    )
                },
            }

        if mtype == "utilization":
            _site_rows = self.journal.list_sites()
            return {
                "type": "utilization",
                "payload": {
                    "sites": [
                        procurement.site_utilization(self.journal, s["id"])
                        for s in _site_rows
                    ]
                },
            }

        return {"type": "error", "payload": {"error": f"unknown message type: {mtype}"}}

    async def run(self) -> None:
        gameplay.bootstrap_if_empty(self.journal)
        self.scheduler.rehydrate()
        await self.ipc.start()
        self.journal.append("daemon_start", "INFO", {"time": iso(now_utc())})
        # Make sure at least one outage roll is queued; rehydrate covers
        # follow-ons once one has been scheduled.
        pending_kinds = {p["kind"] for p in self.journal.pending()}
        if "outage_roll" not in pending_kinds:
            outages.schedule_next_roll(self.scheduler.add)
        if "payroll_run" not in pending_kinds:
            payroll.schedule_next_payroll(self.scheduler.add)
        if "staff_agent_tick" not in pending_kinds:
            agents.schedule_next_tick(self.scheduler.add)
        print(
            f"SCP daemon listening on {self.ipc.host}:{self.ipc.port}, "
            f"db {self.journal.db_path}"
        )
        sched_task = asyncio.create_task(self.scheduler.run())
        shutdown_task = asyncio.create_task(self._shutdown.wait())
        done, pending = await asyncio.wait(
            [sched_task, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self.journal.append("daemon_stop", "INFO", {"time": iso(now_utc())})
        print("daemon shutting down cleanly")


def main() -> None:
    d = Daemon()
    try:
        asyncio.run(d.run())
    except KeyboardInterrupt:
        print("\ndaemon shutting down")
    finally:
        d.journal.close()


if __name__ == "__main__":
    main()
