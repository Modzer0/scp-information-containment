from __future__ import annotations

from datetime import datetime, timedelta, timezone
from difflib import get_close_matches

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static

from .client import DaemonClient
from .events import SubscriptionClient
from .format import humanize_duration, humanize_eta, humanize_money


HINT = "type 'help' for commands, 'sitrep' for a full dashboard, 'next' for imminent events"


HELP_TOPICS = {
    "ops": {
        "title": "Operations",
        "commands": [
            ("scan", "Start a scan; candidates surface at completion"),
            ("items [state]", "List items (filter: candidate|quarantined|analyzed|archived|...)"),
            ("item <id>", "Full detail for a single item"),
            ("acquire <item>", "Move a candidate to quarantine"),
            ("analyze <item> <vm> [override]", "Analyze an item on a VM (override bypasses soft rail)"),
            ("archive <item>", "Archive an analyzed item; funding awarded"),
            ("wipe <host>", "Forensic wipe + reprovision a compromised host"),
        ],
    },
    "fleet": {
        "title": "Fleet (aircraft / ships / submarines)",
        "commands": [
            ("aircraft", "List owned aircraft"),
            ("ships", "List owned surface ships"),
            ("submarines", "List owned submarines"),
            ("transport_methods", "Show truck / air / rail / sea methods"),
            ("transfer_item <item> <site> [method]", "Ship an archived item between sites"),
            ("relocate_host <host> <site> [method]", "Move compute between sites"),
            ("reassign_staff <staff> <site>", "Send staff between sites"),
        ],
    },
    "sites": {
        "title": "Sites + infrastructure",
        "commands": [
            ("site_types", "List buildable site types"),
            ("establish_site <type> <name>", "Order a new site"),
            ("vms", "List VMs + containment + host status"),
            ("vm <id>", "Full VM containment breakdown with component bars"),
            ("hosts", "List hosts"),
            ("host <id>", "Host specs + VMs on it"),
            ("networks", "List network tiers"),
            ("upgrade_network <site> <tier>", "Change site connectivity (private_sat requires sat + ground station)"),
        ],
    },
    "orbit": {
        "title": "Orbital infrastructure",
        "commands": [
            ("satellites", "List on-orbit satellites (comms/storage/compute/sigint/imint/otv)"),
            ("buy <satellite-sku>", "Launch a new satellite"),
            ("buy portable_uplink <site>", "Install ground station"),
            ("upgrade_network <site> private_sat", "Route site through owned sat (no encryption gate)"),
        ],
    },
    "finance": {
        "title": "Finance + procurement",
        "commands": [
            ("catalog [cat]", "Browse hardware SKUs"),
            ("buy <sku> [target_id]", "Place an order"),
            ("purchases", "Orders in flight + installed history"),
            ("contract_types", "List subscription types"),
            ("subscribe <type> <target>", "Start a recurring subscription"),
            ("contracts", "Active / lapsed / cancelled subscriptions"),
            ("cancel_contract <id>", "End a subscription"),
        ],
    },
    "staff": {
        "title": "Staff + training",
        "commands": [
            ("staff", "List roster with skills + clearance"),
            ("courses", "Training courses with prereqs"),
            ("enroll <staff> <course>", "Start training"),
            ("enrollments", "Training in flight + graduations"),
        ],
    },
    "playbooks": {
        "title": "Playbooks (autonomy)",
        "commands": [
            ("playbook_rules", "List known auto-rules"),
            ("playbooks", "Show per-site enabled rules"),
            ("playbook <site> <rule> on|off", "Toggle auto-rule for a site"),
        ],
    },
    "incidents": {
        "title": "Incidents + learning",
        "commands": [
            ("incidents", "List incident reports"),
            ("incident <id>", "Print full formatted incident report"),
            ("mistakes", "Recent mistake detections"),
        ],
    },
    "daemon": {
        "title": "Daemon / session",
        "commands": [
            ("sitrep", "Full situation dashboard"),
            ("next", "Imminent pending events with ETAs"),
            ("recent", "Recent journal entries"),
            ("pending", "Scheduled events not yet fired"),
            ("power_plants", "Installed power plants (gensets, solar, reactors)"),
            ("outages", "Active grid / ISP outages"),
            ("trigger_outage <site> [h]", "Force an outage for testing"),
            ("ping", "Daemon round-trip"),
            ("quit", "Exit TUI (daemon keeps running)"),
            ("shutdown --confirm", "Stop the daemon gracefully (ALL activity halts)"),
            ("reset", "Wipe all state and start a fresh simulation (interactive YES prompt)"),
        ],
    },
}


class ScpTui(App):
    CSS = """
    Screen { layout: vertical; }
    #clock { height: 1; padding: 0 1; background: $panel; color: $accent; }
    #help  { height: 1; padding: 0 1; color: $text-muted; }
    #journal { height: 1fr; border: solid $accent; }
    #statusbar { height: 1; padding: 0 1; background: $panel; }
    #cmd { dock: bottom; }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+d", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.client = DaemonClient()
        self.subscriber: SubscriptionClient | None = None
        self.clock_widget: Static | None = None
        self.log_widget: RichLog | None = None
        self.status_widget: Static | None = None
        self._known_verbs: list[str] = []
        # Pending verification prompt (set when an action requires YES to proceed)
        self._pending_confirm: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("connecting...", id="clock")
        yield Static(HINT, id="help")
        with Vertical():
            yield RichLog(id="journal", highlight=True, markup=True, wrap=True)
        yield Static("[dim]status: —[/]", id="statusbar")
        yield Input(placeholder="> ", id="cmd")
        yield Footer()

    async def on_mount(self) -> None:
        self.clock_widget = self.query_one("#clock", Static)
        self.log_widget = self.query_one("#journal", RichLog)
        self.status_widget = self.query_one("#statusbar", Static)
        try:
            await self.client.connect()
            self._log(
                f"[green]connected to daemon[/] {self.client.host}:{self.client.port}"
            )
            # Live event stream over a second socket
            self.subscriber = SubscriptionClient(
                self.client.host, self.client.port, self._on_live_event
            )
            try:
                await self.subscriber.start()
                self._log("[green]live event stream active[/]")
            except Exception as exc:
                self._log(f"[yellow]event stream unavailable: {exc}[/]")
            await self.refresh_recent()
            await self._show_sitrep()
            await self._refresh_statusbar()
        except Exception as exc:
            self._log(f"[red]connect failed: {exc}[/]  — is the daemon running?")
        self.set_interval(1.0, self.tick_clock)
        # Refresh statusbar every 3s as a safety net
        self.set_interval(3.0, self._tick_statusbar)
        self.query_one("#cmd", Input).focus()

    async def _tick_statusbar(self) -> None:
        try:
            await self._refresh_statusbar()
        except Exception:
            pass

    async def _on_live_event(self, msg: dict) -> None:
        if msg.get("type") != "event_fired":
            return
        p = msg.get("payload", {})
        sev = p.get("severity", "INFO")
        color = self._color_for_sev(sev)
        kind = p.get("kind", "?")
        message = p.get("message", "")
        self._log(f"[{color}]● {sev:7s}[/] [bold]{kind:22s}[/] {message}")
        # Refresh the status bar on every live event — funding/pending may have changed
        try:
            await self._refresh_statusbar()
        except Exception:
            pass

    async def _refresh_statusbar(self) -> None:
        if self.status_widget is None:
            return
        try:
            sitrep_reply = await self.client.send({"type": "sitrep"})
            pending_reply = await self.client.send({"type": "list_events"})
            outages_reply = await self.client.send({"type": "list_outages"})
        except Exception:
            return
        s = sitrep_reply.get("payload", {})
        pending = pending_reply.get("payload", {}).get("pending", [])
        outages = outages_reply.get("payload", {}).get("outages", [])
        hard_outages = [o for o in outages if not o.get("ride_through")]
        funding = s.get("funding", 0)
        over_sites = sum(
            1 for u in s.get("utilization", [])
            if u.get("power_over") or u.get("cooling_over") or u.get("fuel_starved")
        )
        alerts = len(hard_outages) + over_sites + s.get("open_incidents", 0)
        alert_color = "red" if alerts else "green"
        outage_color = "red" if hard_outages else ("yellow" if outages else "green")
        status = (
            f"[green]Funds[/] {humanize_money(funding):<10}  "
            f"[cyan]Pending[/] {len(pending):<3}  "
            f"[cyan]Contracts[/] {s.get('active_contracts', 0):<3}  "
            f"[{outage_color}]Outages[/] {len(outages):<2}  "
            f"[{alert_color}]Alerts[/] {alerts}"
        )
        self.status_widget.update(status)

    def _log(self, line: str) -> None:
        if self.log_widget is not None:
            self.log_widget.write(line)

    def tick_clock(self) -> None:
        now = datetime.now(timezone.utc)
        if self.clock_widget is not None:
            self.clock_widget.update(f"UTC {now.isoformat(timespec='seconds')}")

    async def refresh_recent(self) -> None:
        try:
            reply = await self.client.send(
                {"type": "recent_journal", "payload": {"limit": 20}}
            )
        except Exception as exc:
            self._log(f"[red]err refresh_recent: {exc}[/]")
            return
        entries = reply.get("payload", {}).get("entries", [])
        for e in reversed(entries):
            self._log(self._fmt_entry(e))

    @staticmethod
    def _color_for_sev(sev: str) -> str:
        return {
            "INFO": "cyan",
            "NOTICE": "yellow",
            "WARNING": "yellow",
            "ALERT": "red",
            "BREACH": "bold red",
            "ERROR": "bold red",
        }.get(sev, "white")

    def _fmt_entry(self, e: dict) -> str:
        sev = e.get("severity", "INFO")
        color = self._color_for_sev(sev)
        summary = self._summarize_payload(e["kind"], e.get("payload", {}))
        ts = humanize_eta(e["ts"])
        return (
            f"[{color}]{sev:7s}[/] {ts:>12}  "
            f"[cyan]{e['kind']:26s}[/] {summary}"
        )

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        cmd = event.value.strip()
        event.input.value = ""
        if not cmd:
            return
        try:
            await self.execute(cmd)
        except (ConnectionError, BrokenPipeError) as exc:
            self._log(f"[yellow]daemon dropped ({exc}); attempting reconnect...[/]")
            await self._reconnect()
        except Exception as exc:
            self._log(f"[red]err: {exc}[/]")

    async def _do_reset(self) -> None:
        try:
            reply = await self.client.send(
                {"type": "reset", "payload": {"reason": "tui reset --confirm"}}
            )
        except Exception as exc:
            self._log(f"[red]reset request failed: {exc}[/]")
            return
        if reply.get("type") == "error":
            self._log(f"[red]reset failed:[/] {reply.get('payload', {}).get('error')}")
            return
        self._log("[bold green]state reset — fresh simulation bootstrapped[/]")
        try:
            await self.refresh_recent()
            await self._show_sitrep()
            await self._refresh_statusbar()
        except Exception:
            pass

    async def _reconnect(self) -> None:
        try:
            await self.client.close()
        except Exception:
            pass
        try:
            await self.client.connect()
            self._log("[green]reconnected to daemon[/]")
            # Re-establish event stream too
            if self.subscriber is not None:
                try:
                    await self.subscriber.stop()
                except Exception:
                    pass
            self.subscriber = SubscriptionClient(
                self.client.host, self.client.port, self._on_live_event
            )
            try:
                await self.subscriber.start()
                self._log("[green]event stream reattached[/]")
            except Exception as e:
                self._log(f"[yellow]event stream failed: {e}[/]")
        except Exception as e:
            self._log(f"[red]reconnect failed: {e}[/]  (retry a command to try again)")

    async def execute(self, cmd: str) -> None:
        # If an action is awaiting verification, treat this input as the
        # response. Only "YES" (case-insensitive) proceeds; anything else
        # cancels, and the typed text is NOT run as a command.
        if self._pending_confirm is not None:
            pending = self._pending_confirm
            self._pending_confirm = None
            if cmd.strip().upper() == "YES":
                if pending == "reset":
                    await self._do_reset()
                return
            self._log(f"[dim]{pending} cancelled[/]")
            return

        parts = cmd.split()
        verb = parts[0].lower()

        if verb in ("quit", "exit"):
            self.exit()
            return

        if verb == "reset":
            self._pending_confirm = "reset"
            self._log(
                "[bold red]CAUTION:[/] this deletes ALL state — sites, fleets, "
                "staff, incidents, journal, funding balance, scheduled jobs."
            )
            self._log(
                "[yellow]type [bold]YES[/] (anything else cancels):[/]"
            )
            return

        if verb == "shutdown":
            if len(parts) < 2 or parts[1] != "--confirm":
                self._log(
                    "[yellow]this stops the background daemon — ALL activity halts.[/]\n"
                    "[yellow]re-issue as:[/]  [bold]shutdown --confirm[/]"
                )
                return
            try:
                reply = await self.client.send({"type": "shutdown"})
                self._log(
                    f"[red]daemon acknowledging shutdown:[/] "
                    f"{reply.get('payload', {})}"
                )
                self._log(
                    "[dim]connection will drop shortly — TUI can exit with 'quit'[/]"
                )
            except Exception as e:
                self._log(f"[red]shutdown request failed:[/] {e}")
            return

        if verb == "help":
            topic = parts[1].lower() if len(parts) > 1 else None
            self._show_help(topic)
            return

        if verb == "ping":
            reply = await self.client.send({"type": "ping"})
            self._log(f"[green]pong[/] {reply.get('payload', {})}")
            return

        if verb == "recent":
            await self.refresh_recent()
            return

        if verb == "pending":
            reply = await self.client.send({"type": "list_events"})
            pending = reply.get("payload", {}).get("pending", [])
            if not pending:
                self._log("[dim]no pending events[/]")
            for p in pending:
                self._log(
                    f"[yellow]#{p['id']:<4}[/] {humanize_eta(p['eta']):>14}  "
                    f"{p['kind']:22s} {self._summarize_payload(p['kind'], p['payload'])}"
                )
            return

        if verb == "next":
            # Same data as pending, but formatted as an upcoming schedule
            reply = await self.client.send({"type": "list_events"})
            pending = reply.get("payload", {}).get("pending", [])
            if not pending:
                self._log("[dim]schedule is clear[/]")
                return
            self._log("[bold cyan]-- next 10 events --[/]")
            for p in pending[:10]:
                self._log(
                    f"  [yellow]{humanize_eta(p['eta']):>14}[/]  "
                    f"[cyan]{p['kind']:22s}[/] "
                    f"{self._summarize_payload(p['kind'], p['payload'])}"
                )
            return

        if verb == "sitrep":
            await self._show_sitrep()
            return

        if verb == "scan":
            reply = await self.client.send({"type": "scan"})
            self._log_reply("scan", reply)
            return

        if verb == "items":
            state = parts[1] if len(parts) > 1 else None
            reply = await self.client.send(
                {"type": "list_items", "payload": {"state": state} if state else {}}
            )
            items = reply.get("payload", {}).get("items", [])
            if not items:
                self._log("[dim]no items[/]")
            for it in items:
                self._log(self._fmt_item(it))
            return

        if verb == "vms":
            reply = await self.client.send({"type": "list_vms"})
            vms = reply.get("payload", {}).get("vms", [])
            if not vms:
                self._log("[dim]no vms[/]")
            for v in vms:
                self._log(self._fmt_vm(v))
            return

        if verb == "hosts":
            reply = await self.client.send({"type": "list_hosts"})
            hosts = reply.get("payload", {}).get("hosts", [])
            for h in hosts:
                self._log(
                    f"[cyan]host[/] id={h['id']} {h['name']} class={h['class']} "
                    f"status=[bold]{h['status']}[/]"
                )
            return

        if verb == "staff":
            reply = await self.client.send({"type": "list_staff"})
            roster = reply.get("payload", {}).get("staff", [])
            for s in roster:
                is_player = "[bold green](you)[/]" if s["is_player"] else ""
                sk = " ".join(f"{k}={v}" for k, v in s["skills"].items())
                self._log(
                    f"[cyan]staff {s['id']}[/] {s['name']} "
                    f"role={s['role']} clearance=L{s['clearance']} "
                    f"status={s['status']} {is_player} [{sk}]"
                )
            return

        if verb == "acquire":
            if len(parts) < 2:
                self._log("[yellow]usage: acquire <item_id>[/]")
                return
            reply = await self.client.send(
                {"type": "acquire", "payload": {"item_id": int(parts[1])}}
            )
            self._log_reply("acquire", reply)
            return

        if verb == "analyze":
            if len(parts) < 3:
                self._log("[yellow]usage: analyze <item_id> <vm_id> [override][/]")
                return
            override = any(p.lower() == "override" for p in parts[3:])
            reply = await self.client.send(
                {
                    "type": "analyze",
                    "payload": {
                        "item_id": int(parts[1]),
                        "vm_id": int(parts[2]),
                        "override": override,
                    },
                }
            )
            self._log_analyze_reply(reply)
            return

        if verb == "archive":
            if len(parts) < 2:
                self._log("[yellow]usage: archive <item_id>[/]")
                return
            reply = await self.client.send(
                {"type": "archive", "payload": {"item_id": int(parts[1])}}
            )
            self._log_reply("archive", reply)
            return

        if verb == "wipe":
            if len(parts) < 2:
                self._log("[yellow]usage: wipe <host_id>[/]")
                return
            reply = await self.client.send(
                {"type": "wipe", "payload": {"host_id": int(parts[1])}}
            )
            self._log_reply("wipe", reply)
            return

        if verb == "incidents":
            reply = await self.client.send({"type": "list_incidents"})
            incs = reply.get("payload", {}).get("incidents", [])
            if not incs:
                self._log("[dim]no incidents on record[/]")
            for i in incs:
                color = self._color_for_sev(i["severity"])
                self._log(
                    f"[{color}]INC#{i['id']:<4} {i['severity']:7s}[/] {i['ts']}  "
                    f"item={i['item_id']} host={i['host_id']} "
                    f"root: {i['root_cause']}"
                )
            return

        if verb == "incident":
            if len(parts) < 2:
                self._log("[yellow]usage: incident <id>[/]")
                return
            reply = await self.client.send(
                {"type": "get_incident", "payload": {"id": int(parts[1])}}
            )
            if reply.get("type") == "error":
                self._log(f"[red]{reply['payload'].get('error')}[/]")
                return
            inc = reply["payload"]
            self._log(f"[bold]{'-' * 60}[/]")
            for line in inc["report"].splitlines():
                self._log(line)
            self._log(f"[bold]{'-' * 60}[/]")
            return

        if verb == "catalog":
            category = parts[1] if len(parts) > 1 else None
            reply = await self.client.send(
                {"type": "catalog", "payload": {"category": category} if category else {}}
            )
            p = reply.get("payload", {})
            # Count owned assets by SKU for ownership badges
            ownership = await self._owned_by_sku()
            self._log(f"[dim]categories:[/] {', '.join(p.get('categories', []))}")
            for s in p.get("skus", []):
                badge = ""
                owned = ownership.get(s["sku"], 0)
                if owned:
                    badge = f"  [bold green][owned: {owned}][/]"
                self._log(self._fmt_sku(s) + badge)
            return

        if verb == "buy":
            if len(parts) < 2:
                self._log("[yellow]usage: buy <sku> [target_id][/]")
                return
            sku = parts[1]
            payload: dict = {"sku": sku}
            if len(parts) > 2:
                target_id = int(parts[2])
                # Infer target type by SKU category — look it up via catalog
                cat_reply = await self.client.send({"type": "catalog"})
                skus = cat_reply.get("payload", {}).get("skus", [])
                sku_info = next((x for x in skus if x["sku"] == sku), None)
                if sku_info and sku_info["category"] == "vm_module":
                    payload["target_vm_id"] = target_id
                else:
                    payload["target_site_id"] = target_id
            reply = await self.client.send({"type": "buy", "payload": payload})
            self._log_reply("buy", reply)
            return

        if verb == "purchases":
            reply = await self.client.send({"type": "list_purchases"})
            purchases = reply.get("payload", {}).get("purchases", [])
            if not purchases:
                self._log("[dim]no purchases on record[/]")
            for p in purchases:
                color = {"ordered": "yellow", "installed": "green"}.get(
                    p["status"], "white"
                )
                if p["target_site_id"]:
                    tgt = f"site={p['target_site_id']}"
                elif p["target_vm_id"]:
                    tgt = f"vm={p['target_vm_id']}"
                else:
                    tgt = ""
                eta_s = humanize_eta(p["eta_utc"]) if p["status"] == "ordered" else "installed"
                self._log(
                    f"[{color}]#{p['id']:<3} {p['status']:10s}[/] "
                    f"{p['sku']:25s} {humanize_money(p['price_usd']):>10} "
                    f"{eta_s:>14}  {tgt}"
                )
            return

        if verb == "aircraft":
            reply = await self.client.send({"type": "list_aircraft"})
            acs = reply.get("payload", {}).get("aircraft", [])
            if not acs:
                self._log("[dim]no aircraft on roster[/]")
            for a in acs:
                self._log(
                    f"[cyan]{a['tail_number']}[/] {a['sku']:20s} "
                    f"class={a['class']}  @site {a['site_id']}  "
                    f"status=[bold]{a['status']}[/]"
                )
            return

        if verb == "ships":
            reply = await self.client.send({"type": "list_ships"})
            ss = reply.get("payload", {}).get("ships", [])
            if not ss:
                self._log("[dim]no ships on roster[/]")
            for s in ss:
                self._log(
                    f"[cyan]{s['hull_number']}[/] {s['sku']:20s} "
                    f"class={s['class']}  @site {s['site_id']}  "
                    f"status=[bold]{s['status']}[/]"
                )
            return

        if verb == "satellites":
            reply = await self.client.send({"type": "list_satellites"})
            sats = reply.get("payload", {}).get("satellites", [])
            if not sats:
                self._log("[dim]no satellites on orbit[/]")
            for s in sats:
                color = {
                    "on_orbit": "green",
                    "commissioning": "yellow",
                    "defunct": "red",
                }.get(s["status"], "white")
                self._log(
                    f"[{color}]{s['callsign']}[/] {s['sku']:25s} "
                    f"{s['class']:10s} orbit={s['orbit']:4s} "
                    f"payload={s['payload']:8s} [{s['status']}]"
                )
            return

        if verb == "outages":
            reply = await self.client.send({"type": "list_outages"})
            outs = reply.get("payload", {}).get("outages", [])
            if not outs:
                self._log("[dim]no active outages[/]")
            for o in outs:
                color = "red" if not o["ride_through"] else "yellow"
                ride = "ride-through" if o["ride_through"] else "[red]DARK[/]"
                self._log(
                    f"[{color}]#{o['id']:<3} {o['kind']:11s}[/] "
                    f"site {o['site_id']}  {o['duration_h']:.1f}h  "
                    f"ends {humanize_eta(o['eta_end_utc'])}  [{ride}]"
                )
            return

        if verb == "trigger_outage":
            if len(parts) < 2:
                self._log("[yellow]usage: trigger_outage <site_id> [duration_h][/]")
                return
            dur = float(parts[2]) if len(parts) > 2 else 4.0
            reply = await self.client.send(
                {
                    "type": "trigger_outage",
                    "payload": {"site_id": int(parts[1]), "duration_h": dur},
                }
            )
            self._log_reply("trigger_outage", reply)
            return

        if verb == "power_plants":
            reply = await self.client.send({"type": "list_power_plants"})
            plants = reply.get("payload", {}).get("power_plants", [])
            if not plants:
                self._log("[dim]no power plants installed[/]")
            for pp in plants:
                color = {
                    "online": "green",
                    "offline": "red",
                    "maintenance": "yellow",
                }.get(pp["status"], "white")
                self._log(
                    f"[{color}]#{pp['id']:<3}[/] {pp['plant_type']:12s} "
                    f"{pp['kw_rating']:>5} kW  @site {pp['site_id']}  "
                    f"{pp['sku']:25s} [{pp['status']}]"
                )
            return

        if verb == "submarines":
            reply = await self.client.send({"type": "list_submarines"})
            subs = reply.get("payload", {}).get("submarines", [])
            if not subs:
                self._log("[dim]no submarines on roster[/]")
            for s in subs:
                self._log(
                    f"[cyan]{s['hull_number']}[/] {s['sku']:22s} "
                    f"class={s['class']:6s} @site {s['site_id']} "
                    f"[bold]{s['status']}[/]"
                )
            return

        if verb == "transport_methods":
            reply = await self.client.send({"type": "transport_methods"})
            for m in reply.get("payload", {}).get("methods", []):
                dur = m.get("duration_s", 0)
                if dur < 3600:
                    dur_s = f"{dur/60:.0f}m"
                else:
                    dur_s = f"{dur/3600:.0f}h"
                self._log(
                    f"[cyan]{m['method_id']:8s}[/] {m['name']:25s} "
                    f"${m['cost_per_move']:>6,}  ETA~{dur_s}  "
                    f"[dim]{m['description']}[/]"
                )
            return

        if verb == "transfer_item":
            if len(parts) < 3:
                self._log(
                    "[yellow]usage: transfer_item <item_id> <to_site_id> [method][/]"
                )
                return
            method = parts[3] if len(parts) > 3 else "truck"
            reply = await self.client.send(
                {
                    "type": "transfer_item",
                    "payload": {
                        "item_id": int(parts[1]),
                        "to_site_id": int(parts[2]),
                        "method_id": method,
                    },
                }
            )
            self._log_reply("transfer_item", reply)
            return

        if verb == "relocate_host":
            if len(parts) < 3:
                self._log(
                    "[yellow]usage: relocate_host <host_id> <to_site_id> [method][/]"
                )
                return
            method = parts[3] if len(parts) > 3 else "truck"
            reply = await self.client.send(
                {
                    "type": "relocate_host",
                    "payload": {
                        "host_id": int(parts[1]),
                        "to_site_id": int(parts[2]),
                        "method_id": method,
                    },
                }
            )
            self._log_reply("relocate_host", reply)
            return

        if verb == "reassign_staff":
            if len(parts) < 3:
                self._log(
                    "[yellow]usage: reassign_staff <staff_id> <to_site_id>[/]"
                )
                return
            reply = await self.client.send(
                {
                    "type": "reassign_staff",
                    "payload": {
                        "staff_id": int(parts[1]),
                        "to_site_id": int(parts[2]),
                    },
                }
            )
            self._log_reply("reassign_staff", reply)
            return

        if verb == "site_types":
            reply = await self.client.send({"type": "site_types"})
            for t in reply.get("payload", {}).get("types", []):
                lead = t.get("lead_time_s", 0)
                if lead < 86400:
                    lead_s = f"{lead/3600:.0f}h"
                else:
                    lead_s = f"{lead/86400:.0f}d"
                diesel = " [yellow]needs diesel[/]" if t.get("requires_diesel") else ""
                self._log(
                    f"[cyan]{t['type_id']:15s}[/] ${t['capex_usd']:>10,}  "
                    f"lead={lead_s:>4}  {t['power_kw']:>3}kW power  "
                    f"default={t['default_network']}{diesel}  "
                    f"[dim]{t['description']}[/]"
                )
            return

        if verb == "establish_site":
            if len(parts) < 3:
                self._log("[yellow]usage: establish_site <type_id> <name>[/]")
                return
            # Join remaining words as the name
            name = " ".join(parts[2:])
            reply = await self.client.send(
                {
                    "type": "establish_site",
                    "payload": {"type_id": parts[1], "name": name},
                }
            )
            self._log_reply("establish_site", reply)
            return

        if verb == "playbook_rules":
            reply = await self.client.send({"type": "playbook_rules"})
            for r in reply.get("payload", {}).get("rules", []):
                self._log(f"[cyan]{r['rule']:25s}[/] [dim]{r['description']}[/]")
            return

        if verb == "playbooks":
            reply = await self.client.send({"type": "playbooks"})
            pbs = reply.get("payload", {}).get("playbooks", [])
            if not pbs:
                self._log("[dim]no playbooks configured[/]")
            for p in pbs:
                enabled = [k for k, v in p["rules"].items() if v]
                self._log(
                    f"[cyan]site {p['site_id']}[/] enabled: "
                    f"{', '.join(enabled) if enabled else '[dim]none[/]'}"
                )
            return

        if verb == "playbook":
            if len(parts) < 4:
                self._log("[yellow]usage: playbook <site_id> <rule> on|off[/]")
                return
            enabled = parts[3].lower() in ("on", "true", "1", "yes")
            reply = await self.client.send(
                {
                    "type": "set_playbook_rule",
                    "payload": {
                        "site_id": int(parts[1]),
                        "rule": parts[2],
                        "enabled": enabled,
                    },
                }
            )
            self._log_reply("playbook", reply)
            return

        if verb == "networks":
            reply = await self.client.send({"type": "network_tiers"})
            for t in reply.get("payload", {}).get("tiers", []):
                self._log(
                    f"[cyan]{t['tier']:16s}[/] {t['bandwidth_mbps']:>6} Mbps  "
                    f"lat p50={t['latency_p50_ms']:>3}ms p99={t['latency_p99_ms']:>3}ms  "
                    f"${t['monthly_cost_usd']:>5,}/mo  [dim]{t['description']}[/]"
                )
            return

        if verb == "upgrade_network":
            if len(parts) < 3:
                self._log("[yellow]usage: upgrade_network <site_id> <tier>[/]")
                return
            reply = await self.client.send(
                {
                    "type": "upgrade_network",
                    "payload": {"site_id": int(parts[1]), "tier": parts[2]},
                }
            )
            self._log_reply("upgrade_network", reply)
            return

        if verb == "contract_types":
            reply = await self.client.send({"type": "contract_types"})
            for t in reply.get("payload", {}).get("types", []):
                per = t["period_seconds"]
                if per < 3600:
                    per_s = f"{per/60:.0f}m"
                elif per < 86400:
                    per_s = f"{per/3600:.0f}h"
                else:
                    per_s = f"{per/86400:.0f}d"
                self._log(
                    f"[cyan]{t['type_id']:20s}[/] target={t['target']:4s}  "
                    f"${t['cost_per_period']:>6,} / {per_s}  [dim]{t['description']}[/]"
                )
            return

        if verb == "subscribe":
            if len(parts) < 3:
                self._log("[yellow]usage: subscribe <type_id> <target_id>[/]")
                return
            reply = await self.client.send({"type": "contract_types"})
            types = reply.get("payload", {}).get("types", [])
            tinfo = next((x for x in types if x["type_id"] == parts[1]), None)
            payload: dict = {"type_id": parts[1]}
            target_id = int(parts[2])
            target_kind = tinfo["target"] if tinfo else "site"
            if target_kind == "vm":
                payload["target_vm_id"] = target_id
            elif target_kind in ("aircraft", "ship"):
                payload["target_asset_id"] = target_id
            else:
                payload["target_site_id"] = target_id
            reply = await self.client.send({"type": "subscribe", "payload": payload})
            self._log_reply("subscribe", reply)
            return

        if verb == "contracts":
            reply = await self.client.send({"type": "list_contracts"})
            cs = reply.get("payload", {}).get("contracts", [])
            if not cs:
                self._log("[dim]no contracts[/]")
            for c in cs:
                color = {
                    "active": "green", "lapsed": "red", "cancelled": "dim"
                }.get(c["status"], "white")
                if c["target_vm_id"] is not None:
                    # For aircraft/ship contracts the asset id is stashed here.
                    label = (
                        "asset" if c["contract_type"] in ("jet_a_supply", "bunker_fuel")
                        else "vm"
                    )
                    tgt = f"{label}={c['target_vm_id']}"
                elif c["target_site_id"] is not None:
                    tgt = f"site={c['target_site_id']}"
                else:
                    tgt = ""
                next_s = (
                    humanize_eta(c["next_billing_utc"])
                    if c["status"] == "active" else c["status"]
                )
                self._log(
                    f"[{color}]#{c['id']:<3} {c['status']:10s}[/] "
                    f"{c['contract_type']:16s} {tgt:10s} "
                    f"{humanize_money(c['cost_per_period']):>8}/bill  "
                    f"next {next_s}"
                )
            return

        if verb == "cancel_contract":
            if len(parts) < 2:
                self._log("[yellow]usage: cancel_contract <id>[/]")
                return
            reply = await self.client.send(
                {"type": "cancel_contract", "payload": {"contract_id": int(parts[1])}}
            )
            self._log_reply("cancel_contract", reply)
            return

        if verb == "courses":
            reply = await self.client.send({"type": "courses"})
            courses = reply.get("payload", {}).get("courses", [])
            for c in courses:
                dur = c.get("duration_s", 0)
                if dur < 3600:
                    dur_s = f"{dur/60:.0f}m"
                elif dur < 86400:
                    dur_s = f"{dur/3600:.0f}h"
                else:
                    dur_s = f"{dur/86400:.0f}d"
                prereq = f" (prereq: {c['prereq_course_id']})" if c.get("prereq_course_id") else ""
                self._log(
                    f"[cyan]{c['course_id']:20s}[/] ${c['cost_usd']:>7,}  "
                    f"{dur_s:<4}  {c['skill']}+{c['skill_gain']}  "
                    f"[dim]{c['description']}{prereq}[/]"
                )
            return

        if verb == "enroll":
            if len(parts) < 3:
                self._log("[yellow]usage: enroll <staff_id> <course_id>[/]")
                return
            reply = await self.client.send(
                {
                    "type": "enroll",
                    "payload": {
                        "staff_id": int(parts[1]),
                        "course_id": parts[2],
                    },
                }
            )
            self._log_reply("enroll", reply)
            return

        if verb == "enrollments":
            reply = await self.client.send({"type": "list_enrollments"})
            enrs = reply.get("payload", {}).get("enrollments", [])
            if not enrs:
                self._log("[dim]no enrollments on record[/]")
            for e in enrs:
                color = {"enrolled": "yellow", "graduated": "green", "cancelled": "dim"}.get(
                    e["status"], "white"
                )
                eta_s = humanize_eta(e["eta_utc"]) if e["status"] == "enrolled" else "done"
                self._log(
                    f"[{color}]#{e['id']:<3} {e['status']:10s}[/] "
                    f"staff={e['staff_id']} {e['course_id']:20s} {eta_s:>14}"
                )
            return

        if verb == "item":
            if len(parts) < 2:
                self._log("[yellow]usage: item <id>[/]")
                return
            reply = await self.client.send(
                {"type": "list_items", "payload": {}}
            )
            items = reply.get("payload", {}).get("items", [])
            target = next((i for i in items if i["id"] == int(parts[1])), None)
            if not target:
                self._log(f"[red]no item {parts[1]}[/]")
                return
            self._show_item_detail(target)
            return

        if verb == "vm":
            if len(parts) < 2:
                self._log("[yellow]usage: vm <id>[/]")
                return
            reply = await self.client.send({"type": "list_vms"})
            vms = reply.get("payload", {}).get("vms", [])
            target = next((v for v in vms if v["id"] == int(parts[1])), None)
            if not target:
                self._log(f"[red]no vm {parts[1]}[/]")
                return
            self._show_vm_detail(target)
            return

        if verb == "host":
            if len(parts) < 2:
                self._log("[yellow]usage: host <id>[/]")
                return
            reply = await self.client.send({"type": "list_hosts"})
            hosts = reply.get("payload", {}).get("hosts", [])
            target = next((h for h in hosts if h["id"] == int(parts[1])), None)
            if not target:
                self._log(f"[red]no host {parts[1]}[/]")
                return
            self._show_host_detail(target, vms=(await self.client.send({"type": "list_vms"})).get("payload", {}).get("vms", []))
            return

        if verb == "mistakes":
            reply = await self.client.send({"type": "list_mistakes"})
            ms = reply.get("payload", {}).get("mistakes", [])
            if not ms:
                self._log("[dim]no mistakes recorded[/]")
            for m in ms:
                ovr = "[magenta](override)[/]" if m["overridden"] else ""
                self._log(
                    f"[yellow]MISTAKE[/] #{m['id']} {m['ts']}  {m['kind']:25s} "
                    f"action={m['action']} item={m['item_id']} vm={m['vm_id']} {ovr}"
                )
            return

        self._suggest_command(verb)

    def _show_help(self, topic: str | None) -> None:
        if topic is None:
            self._log("[bold cyan]-- help topics --[/]")
            for key, meta in HELP_TOPICS.items():
                self._log(f"  [cyan]{key:10s}[/] {meta['title']}")
            self._log("  [dim]type 'help <topic>' for commands in that topic[/]")
            return
        meta = HELP_TOPICS.get(topic)
        if not meta:
            self._log(f"[yellow]unknown topic: {topic}[/] (try one of "
                      f"{', '.join(HELP_TOPICS)})")
            return
        self._log(f"[bold cyan]-- {meta['title']} --[/]")
        for cmd, desc in meta["commands"]:
            self._log(f"  [cyan]{cmd:38s}[/] [dim]{desc}[/]")

    def _all_known_verbs(self) -> list[str]:
        if self._known_verbs:
            return self._known_verbs
        verbs: set[str] = {"quit", "exit", "help"}
        for topic in HELP_TOPICS.values():
            for cmd, _desc in topic["commands"]:
                # First token of "scan" / "analyze <item> <vm>" / "playbook <site> <rule> on|off"
                verbs.add(cmd.split()[0])
        verbs.update({"item", "vm", "host"})   # detail views not in help topics
        self._known_verbs = sorted(verbs)
        return self._known_verbs

    def _suggest_command(self, verb: str) -> None:
        matches = get_close_matches(verb, self._all_known_verbs(), n=3, cutoff=0.6)
        if matches:
            self._log(
                f"[yellow]unknown:[/] {verb}  "
                f"[dim]did you mean:[/] {', '.join(matches)}  "
                f"[dim](type 'help' for all commands)[/]"
            )
        else:
            self._log(
                f"[yellow]unknown:[/] {verb}  [dim](type 'help' for commands)[/]"
            )

    def _show_item_detail(self, it: dict) -> None:
        p = it.get("profile", {})
        color = {"Safe": "green", "Euclid": "yellow", "Keter": "red"}.get(
            it.get("class", ""), "white"
        )
        self._log(f"[bold]{'-' * 60}[/]")
        self._log(
            f"[{color}]{it['designation']}[/]  "
            f"[{color}]{it['class']}-class[/]  hazard={it['hazard_strength']}"
        )
        self._log(f"  state: {it.get('state')}")
        if it.get("current_site_id") is not None:
            self._log(f"  location: site {it['current_site_id']}")
        if it.get("transit_to_site_id") is not None:
            self._log(f"  in transit to site {it['transit_to_site_id']}")
        if it.get("current_vm_id") is not None:
            self._log(f"  currently on vm {it['current_vm_id']}")
        self._log(f"  form:    {p.get('form', '—')}")
        self._log(f"  effect:  {p.get('effect', '—')}")
        self._log(
            f"  memetic_load={p.get('memetic_load', 0)}  "
            f"cognitohazard={p.get('cognitohazard_class', 0)}  "
            f"self_propagation={p.get('self_propagation', 0)}"
        )
        self._log(f"  created: {it.get('created_at')}")
        self._log(f"  updated: {it.get('updated_at')}")
        self._log(f"[bold]{'-' * 60}[/]")

    def _show_vm_detail(self, v: dict) -> None:
        spec = v.get("spec", {})
        total = sum(int(x) for x in spec.values())
        self._log(f"[bold]{'-' * 60}[/]")
        self._log(f"[cyan]vm {v['id']}[/] {v['name']}  on host {v['host_id']}")
        self._log(
            f"  status: [bold]{v['status']}[/]  "
            f"host status: [bold]{v['host_status']}[/]"
        )
        self._log(f"  [bold]containment = {total}[/]")
        for k in (
            "memory_encryption",
            "isolation",
            "mnestic_firmware",
            "physical_shielding",
            "scanner_freshness",
        ):
            val = int(spec.get(k, 0))
            bar = "█" * val + "·" * max(0, 10 - val)
            self._log(f"    {k:22s} {val:>2}  [dim]{bar}[/]")
        self._log(f"[bold]{'-' * 60}[/]")

    def _show_host_detail(self, h: dict, vms: list[dict]) -> None:
        specs = h.get("specs", {})
        self._log(f"[bold]{'-' * 60}[/]")
        self._log(
            f"[cyan]host {h['id']}[/] {h['name']}  class={h['class']}  "
            f"@site {h['site_id']}  status=[bold]{h['status']}[/]"
        )
        for k, v in specs.items():
            self._log(f"  {k:20s} {v}")
        host_vms = [v for v in vms if v["host_id"] == h["id"]]
        if host_vms:
            self._log(f"  [bold]{len(host_vms)} VM(s):[/]")
            for v in host_vms:
                total = sum(int(x) for x in v.get("spec", {}).values())
                self._log(
                    f"    vm {v['id']} {v['name']}  containment={total}  "
                    f"[{v['status']}]"
                )
        self._log(f"[bold]{'-' * 60}[/]")

    @staticmethod
    def _summarize_payload(kind: str, payload: dict) -> str:
        """Compact per-kind summary for scheduled events + journal rows."""
        if not payload:
            return ""
        # Scheduled-event completions
        if kind == "analyze_complete":
            return f"item {payload.get('item_id')} on vm {payload.get('vm_id')}"
        if kind in ("archive_complete", "transit_complete"):
            return f"item {payload.get('item_id')}"
        if kind == "scan_complete":
            ids = payload.get("item_ids", [])
            return f"{len(ids)} candidate(s)" if ids else ""
        if kind == "wipe_complete":
            return f"host {payload.get('host_id')}"
        if kind == "install_complete":
            name = payload.get("name") or payload.get("sku")
            return f"{name}" if name else f"purchase #{payload.get('purchase_id')}"
        if kind == "host_arrived":
            return f"host {payload.get('host_id')} → site {payload.get('to_site_id')}"
        if kind == "staff_arrived":
            name = payload.get("staff_name") or f"staff {payload.get('staff_id')}"
            return f"{name} → site {payload.get('to_site_id')}"
        if kind == "site_established":
            return f"{payload.get('type_id')} → {payload.get('name')}"
        if kind == "training_complete":
            return (
                f"{payload.get('staff_name')} {payload.get('course_id')} "
                f"{payload.get('skill')} +{payload.get('gain')}"
            )
        if kind == "contract_billing":
            return f"contract #{payload.get('contract_id')}"
        # Journal-side events
        if kind == "scan_started":
            return ""
        if kind == "item_acquired":
            return f"item {payload.get('item_id')}"
        if kind == "analysis_started":
            return (
                f"item {payload.get('item_id')} vm {payload.get('vm_id')} "
                f"{payload.get('item_class')} H={payload.get('hazard')} "
                f"C={payload.get('containment')}"
            )
        if kind in ("analysis_stable", "analysis_slow_leak",
                    "analysis_active_leak", "analysis_catastrophic"):
            return (
                f"Δ={payload.get('delta')} "
                f"item {payload.get('item_id')} vm {payload.get('vm_id')}"
            )
        if kind == "brownout_promoted_leak":
            return f"{payload.get('from')} → {payload.get('to')} on vm {payload.get('vm_id')}"
        if kind == "item_archived":
            reward = payload.get("reward", 0)
            return (
                f"{payload.get('designation')} ({payload.get('class')}) "
                f"+${reward:,} → balance ${payload.get('balance', 0):,}"
            )
        if kind == "purchase_ordered":
            return (
                f"{payload.get('name')} -${payload.get('price_usd', 0):,} "
                f"balance ${payload.get('balance', 0):,}"
            )
        if kind in ("archive_started", "wipe_started"):
            return f"item/host {payload.get('item_id') or payload.get('host_id')}"
        if kind == "host_relocation_started":
            return (
                f"host {payload.get('host_id')} → site {payload.get('to_site_id')} "
                f"via {payload.get('method')} -${payload.get('cost', 0):,}"
            )
        if kind == "staff_travel_started":
            return (
                f"{payload.get('staff_name')} → site {payload.get('to_site_id')} "
                f"-${payload.get('cost', 0):,}"
            )
        if kind == "contract_subscribed":
            return (
                f"{payload.get('type')} -${payload.get('first_period_cost', 0):,} "
                f"first period"
            )
        if kind == "contract_billed":
            return (
                f"#{payload.get('contract_id')} -${payload.get('cost', 0):,} "
                f"balance ${payload.get('balance', 0):,}"
            )
        if kind == "contract_lapsed":
            return f"#{payload.get('contract_id')} {payload.get('type')}"
        if kind == "contract_cancelled":
            return f"#{payload.get('contract_id')} {payload.get('type')}"
        if kind == "enrollment_started":
            return f"{payload.get('staff_name')} {payload.get('course_id')}"
        if kind == "site_establishment_ordered":
            return f"{payload.get('type_id')} → {payload.get('name')}"
        if kind == "network_upgraded":
            return f"site {payload.get('site_id')} → {payload.get('tier')}"
        if kind == "playbook_rule_changed":
            return (
                f"site {payload.get('site_id')} {payload.get('rule')} "
                f"={payload.get('enabled')}"
            )
        if kind == "playbook_triggered":
            rules = payload.get("triggered", [])
            return f"{len(rules)} rule(s) fired"
        if kind == "bootstrap":
            return f"funding ${payload.get('starting_funding', 0):,}"
        if kind == "daemon_start":
            return ""
        # Fallback: one-line dict (truncated)
        items = list(payload.items())[:3]
        return ", ".join(f"{k}={v}" for k, v in items)

    def _log_reply(self, verb: str, reply: dict) -> None:
        if reply.get("type") == "error":
            self._log(f"[red]✗ {verb}:[/] {reply['payload'].get('error')}")
            return
        p = reply.get("payload", {})
        summary = self._format_action_reply(verb, p)
        if summary:
            self._log(f"[green]✓ {verb}[/] {summary}")
        else:
            self._log(f"[green]✓ {verb} ok[/] {p}")

    @staticmethod
    def _format_action_reply(verb: str, p: dict) -> str:
        """Human summary of a successful action's ack payload."""
        if not p:
            return ""
        if verb == "scan":
            eta = humanize_eta(p.get("eta"))
            op = p.get("operator", "")
            return f"starting... ETA {eta}  operator={op}"
        if verb == "acquire":
            return f"item {p.get('item_id')} → quarantined (operator {p.get('operator')})"
        if verb == "archive":
            return (
                f"archiving... ETA {humanize_eta(p.get('eta'))}  "
                f"operator={p.get('operator')}"
            )
        if verb == "wipe":
            return (
                f"wiping... ETA {humanize_eta(p.get('eta'))}  "
                f"operator={p.get('operator')}"
            )
        if verb == "buy":
            name = p.get("name") or p.get("sku")
            cost = humanize_money(p.get("price_usd", 0))
            bal = humanize_money(p.get("balance", 0))
            eta = humanize_eta(p.get("eta"))
            return f"ordered {name}  -{cost}  balance {bal}  install ETA {eta}"
        if verb == "transfer_item":
            cost = humanize_money(p.get("cost", 0))
            disc = " (owned-asset discount)" if p.get("owned_discount") else ""
            return (
                f"item {p.get('item_id')}  site {p.get('from_site_id')} → "
                f"{p.get('to_site_id')} via {p.get('method')}  -{cost}{disc}  "
                f"ETA {humanize_eta(p.get('eta'))}"
            )
        if verb == "relocate_host":
            return (
                f"host {p.get('host_id')}  site {p.get('from_site_id')} → "
                f"{p.get('to_site_id')} via {p.get('method')}  "
                f"-{humanize_money(p.get('cost', 0))}  "
                f"ETA {humanize_eta(p.get('eta'))}"
            )
        if verb == "reassign_staff":
            return (
                f"{p.get('staff_name')}  site {p.get('from_site_id')} → "
                f"{p.get('to_site_id')}  -{humanize_money(p.get('cost', 0))}  "
                f"ETA {humanize_eta(p.get('eta'))}"
            )
        if verb == "establish_site":
            return (
                f"{p.get('type_id')} '{p.get('name')}'  "
                f"balance {humanize_money(p.get('balance', 0))}  "
                f"ETA {humanize_eta(p.get('eta'))}"
            )
        if verb == "upgrade_network":
            return f"site {p.get('site_id')} → tier '{p.get('tier')}'"
        if verb == "subscribe":
            return (
                f"contract #{p.get('contract_id')} ({p.get('type')})  "
                f"balance {humanize_money(p.get('balance', 0))}  "
                f"next bill {humanize_eta(p.get('next_billing'))}"
            )
        if verb == "cancel_contract":
            return f"contract #{p.get('contract_id')} cancelled"
        if verb == "enroll":
            return (
                f"{p.get('staff_name')} → {p.get('course')}  "
                f"balance {humanize_money(p.get('balance', 0))}  "
                f"ETA {humanize_eta(p.get('eta'))}"
            )
        if verb == "playbook":
            enabled = p.get("rules", {})
            on = [k for k, v in enabled.items() if v]
            return f"site {p.get('site_id')} rules active: {', '.join(on) or 'none'}"
        return ""

    def _log_analyze_reply(self, reply: dict) -> None:
        rtype = reply.get("type")
        p = reply.get("payload", {})
        if rtype == "error":
            self._log(f"[red]analyze error:[/] {p.get('error')}")
            return
        if rtype == "refused":
            self._log(
                f"[bold red]analyze REFUSED (hard rail)[/] — {p.get('refuse_reason')}"
            )
            for w in p.get("warnings", []):
                self._log(f"  [red]• {w}[/]")
            return
        if rtype == "needs_override":
            self._log(
                f"[bold yellow]analyze blocked (soft rail)[/] — {p.get('refuse_reason')}"
            )
            for w in p.get("warnings", []):
                self._log(f"  [yellow]• {w}[/]")
            self._log(
                "[yellow]  re-issue with `override` at the end of the command to proceed[/]"
            )
            return
        # ack — success
        rail = p.get("rail_level", "none")
        self._log(
            f"[green]analyze ok[/] eta={p.get('eta')} operator={p.get('operator')} "
            f"rail={rail}"
        )
        for w in p.get("warnings", []):
            self._log(f"  [yellow]• {w}[/]")

    @staticmethod
    def _fmt_item(it: dict) -> str:
        p = it.get("profile", {})
        color = {
            "Safe": "green",
            "Euclid": "yellow",
            "Keter": "red",
        }.get(it.get("class", ""), "white")
        state = it.get("state", "?")
        form = p.get("form", "")
        site = it.get("current_site_id")
        transit = it.get("transit_to_site_id")
        loc = ""
        if transit is not None:
            loc = f" [yellow]→site {transit}[/]"
        elif site is not None:
            loc = f" @site {site}"
        return (
            f"[{color}]{it['designation']:10s}[/] [{color}]{it['class']:6s}[/] "
            f"H={it['hazard_strength']:<2} state={state:<12} "
            f"id={it['id']}{loc}  {form}"
        )

    @staticmethod
    def _fmt_sku(s: dict) -> str:
        cat_color = {
            "server": "cyan",
            "aipod": "magenta",
            "mainframe": "bold magenta",
            "vm_module": "yellow",
        }.get(s.get("category", ""), "white")
        lead = s.get("lead_time_s", 0)
        if lead < 60:
            lead_str = f"{lead:.0f}s"
        elif lead < 3600:
            lead_str = f"{lead/60:.0f}m"
        elif lead < 86400:
            lead_str = f"{lead/3600:.0f}h"
        else:
            lead_str = f"{lead/86400:.0f}d"
        return (
            f"[{cat_color}]{s['category']:10s}[/] {s['sku']:25s} "
            f"${s['price_usd']:>10,}  {s['power_w']:>5}W  lead={lead_str}  "
            f"[dim]{s.get('description', '')}[/]"
        )

    @staticmethod
    def _fmt_vm(v: dict) -> str:
        spec = v.get("spec", {})
        containment = sum(int(x) for x in spec.values())
        return (
            f"[cyan]vm[/] id={v['id']} {v['name']} on host {v['host_id']} "
            f"containment={containment} status=[bold]{v['status']}[/] "
            f"(host=[bold]{v['host_status']}[/])"
        )

    async def _show_sitrep(self) -> None:
        reply = await self.client.send({"type": "sitrep"})
        s = reply.get("payload", {})
        player = s.get("player") or {}
        skills = player.get("skills", {})
        sk = " ".join(f"{k}={v}" for k, v in skills.items())
        self._log(
            f"[bold cyan]== SITREP ==[/]  "
            f"funding=[green]{humanize_money(s.get('funding', 0))}[/]  "
            f"archived={s.get('archived_count', 0)}  "
            f"incidents={s.get('open_incidents', 0)}  "
            f"orders={s.get('pending_purchases', 0)}  "
            f"contracts={s.get('active_contracts', 0)}"
        )
        self._log(f"  [bold]you[/] L{player.get('clearance', 0)}  [{sk}]")

        # Sites with utilization + network + encryption
        networks = s.get("site_networks", {})
        encryption_map = s.get("site_encryption", {})
        for u in s.get("utilization", []):
            pw_color = "red" if u.get("power_over") else "green"
            cl_color = "red" if u.get("cooling_over") else "green"
            net = networks.get(str(u["site_id"])) or networks.get(u["site_id"]) or {}
            enc = (
                encryption_map.get(str(u["site_id"]))
                or encryption_map.get(u["site_id"])
                or "none"
            )
            enc_color = {
                "none": "red",
                "software": "yellow",
                "hardware": "green",
                "type1": "bold green",
            }.get(enc, "white")
            fuel_tag = ""
            if u.get("fuel_starved"):
                fuel_tag = f" [bold red]FUEL-STARVED[/] (nominal {u.get('power_kw_nominal', 0)}kW)"
            if u.get("outaged"):
                fuel_tag += " [bold red]GRID-DARK[/]"
            ride_h = u.get("ride_through_hours", 0)
            ride_tag = (
                f"  ride≈{ride_h:.0f}h"
                if ride_h > 0 else ""
            )
            self._log(
                f"  [cyan]site {u['site_id']}[/] hosts={u['hosts']}  "
                f"power=[{pw_color}]{u['power_kw_used']:.2f}/"
                f"{u['power_kw_capacity']}kW[/]  "
                f"cooling=[{cl_color}]{u['cooling_kw_used']:.2f}/"
                f"{u['cooling_kw_capacity']}kW[/]  "
                f"net=[dim]{net.get('tier', '?')}[/]  "
                f"enc=[{enc_color}]{enc}[/]{ride_tag}{fuel_tag}"
            )

        # Item buckets (only show non-empty)
        buckets_printed = False
        for bucket in ("candidates", "quarantined", "analyzing", "analyzed", "archiving"):
            items = s.get(bucket, [])
            if items:
                if not buckets_printed:
                    self._log("  [bold]items:[/]")
                    buckets_printed = True
                self._log(f"    [yellow]{bucket}[/] ({len(items)})")

        # Staff summary
        staff = s.get("staff", [])
        if staff:
            active = sum(1 for x in staff if x["status"] == "active")
            training = sum(1 for x in staff if x["status"] == "training")
            traveling = sum(1 for x in staff if x["status"] == "traveling")
            self._log(
                f"  [bold]staff:[/] {len(staff)} total  "
                f"active={active} training={training} traveling={traveling}"
            )

        # Rosters — ask daemon for live counts
        await self._append_fleet_summary()

    async def _owned_by_sku(self) -> dict[str, int]:
        """Count owned assets grouped by their originating SKU."""
        counts: dict[str, int] = {}
        try:
            rosters = [
                ("list_aircraft", "aircraft"),
                ("list_ships", "ships"),
                ("list_submarines", "submarines"),
                ("list_satellites", "satellites"),
            ]
            for verb, key in rosters:
                reply = await self.client.send({"type": verb})
                for a in reply.get("payload", {}).get(key, []):
                    sku = a.get("sku")
                    if sku:
                        counts[sku] = counts.get(sku, 0) + 1
        except Exception:
            pass
        return counts

    async def _append_fleet_summary(self) -> None:
        """Aircraft / ships / submarines / satellites rosters, one line each."""
        try:
            ac = (await self.client.send({"type": "list_aircraft"})).get("payload", {}).get("aircraft", [])
            sh = (await self.client.send({"type": "list_ships"})).get("payload", {}).get("ships", [])
            sb = (await self.client.send({"type": "list_submarines"})).get("payload", {}).get("submarines", [])
            st = (await self.client.send({"type": "list_satellites"})).get("payload", {}).get("satellites", [])
        except Exception:
            return
        if ac:
            maint = sum(1 for a in ac if a["status"] == "maintenance")
            tag = f"  [dim]({maint} in maintenance)[/]" if maint else ""
            self._log(f"  [bold]aircraft:[/] {len(ac)}{tag}")
        if sh:
            maint = sum(1 for x in sh if x["status"] == "maintenance")
            tag = f"  [dim]({maint} in maintenance)[/]" if maint else ""
            self._log(f"  [bold]ships:[/] {len(sh)}{tag}")
        if sb:
            self._log(f"  [bold]submarines:[/] {len(sb)}")
        if st:
            by_payload: dict[str, int] = {}
            for sat in st:
                by_payload[sat["payload"]] = by_payload.get(sat["payload"], 0) + 1
            tags = " ".join(f"{k}×{v}" for k, v in sorted(by_payload.items()))
            self._log(f"  [bold]satellites:[/] {len(st)}  [dim]{tags}[/]")

    async def on_unmount(self) -> None:
        if self.subscriber is not None:
            try:
                await self.subscriber.stop()
            except Exception:
                pass
        await self.client.close()


def main() -> None:
    ScpTui().run()


if __name__ == "__main__":
    main()
