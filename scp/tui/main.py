from __future__ import annotations

from datetime import datetime, timedelta, timezone
from difflib import get_close_matches

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static

from .client import DaemonClient
from .events import SubscriptionClient
from .format import humanize_duration, humanize_eta, humanize_money


HINT = (
    "type 'help' for commands · 'sitrep' for dashboard · 'next' for schedule  "
    "| ↑/↓ history · prefixes auto-complete (e.g. 'sit', 'arc')"
)


HELP_TOPICS = {
    "ops": {
        "title": "Operations",
        "commands": [
            ("scan", "Start a scan; candidates surface at completion"),
            ("items [state]", "List ACTIVE items (archived ones live under `archived`)"),
            ("archived", "Browse archived items by id (for transfer_item / item commands)"),
            ("item <id>", "Full detail for a single item"),
            ("acquire <ids>", "Move candidate(s) to quarantine.  ids: 5 | 3-7 | 1,3,5"),
            ("analyze <item> <vm> [override]", "Analyze an item on a VM (override bypasses soft rail)"),
            ("archive <ids|all> [site]", "Archive analyzed item(s); optional target site = cross-site transmission"),
            ("wipe <host>", "Forensic wipe + reprovision a compromised host"),
        ],
    },
    "fleet": {
        "title": "Fleet (aircraft / ships / submarines)",
        "commands": [
            ("aircraft", "List owned aircraft"),
            ("ships", "List owned surface ships"),
            ("submarines", "List owned submarines"),
            ("vessel <ship|sub> <id>", "Full dashboard for one vessel (equipment, rating, current order)"),
            ("vessel_equipment [ship|submarine] [class]", "Browse installable equipment catalog"),
            ("install_equipment <ship|sub> <id> <sku>", "Install equipment on a vessel (vessel must be berthed)"),
            ("uninstall_equipment <equipment_id>", "Remove installed equipment (vessel must be berthed)"),
            ("order <ship|sub> <id> <kind> [hours] [site]", "Issue an order: patrol | escort_convoy | standby_archive | return_to_port"),
            ("cancel_order <ship|sub> <id>", "Cancel active order (no payout)"),
            ("orders", "List recent vessel orders"),
            ("transport_methods", "Show truck / air / rail / sea / data_link methods"),
            ("transfer_item <ids|all> <site> [method]", "Ship archived items between sites.  data_link = encrypted network transmission"),
            ("relocate_host <host> <site> [method]", "Move compute between sites"),
            ("reassign_staff <ids> <site>", "Send staff between sites.  ids: 2 | 2-5 | 1,3,7"),
        ],
    },
    "sites": {
        "title": "Sites + infrastructure",
        "commands": [
            ("site_types", "List buildable site types"),
            ("site <id>", "Full dashboard for one site (staff, hosts, VMs, power, cooling, storage, fleet, security)"),
            ("security", "Security-rating overview for every site"),
            ("site_security <id>", "Per-site security breakdown: base, equipment, guards, incidents"),
            ("security_catalog", "Browse security-equipment SKUs + guard contract tiers"),
            ("install_security <site> <sku>", "Install security equipment on a site"),
            ("uninstall_security <equipment_id>", "Remove installed security equipment"),
            ("hire_guards <site> <tier>", "Subscribe to a guard contract (monthly billing)"),
            ("establish_site <type> <name>", "Order a new site"),
            ("vms", "List VMs + containment + allocated RAM"),
            ("vm <id>", "Full VM containment breakdown with component bars"),
            ("provision_vm <host_id> [name]", "Create a new VM on a host (inherits host base containment; splits RAM)"),
            ("deprovision_vm <vm_id>", "Tear down a VM; frees its RAM share back to remaining VMs"),
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
            ("catalog [cat]", "Browse hardware SKUs (category hint shown per row)"),
            ("buy <sku> [target_id]", "Place an order — see 'help buying' for targets"),
            ("purchases", "Orders in flight + installed history"),
            ("contract_types", "List subscription types"),
            ("subscribe <type> <target>", "Start a recurring subscription"),
            ("contracts", "Active / lapsed / cancelled subscriptions"),
            ("cancel_contract <id>", "End a subscription"),
        ],
    },
    "buying": {
        "title": "How 'buy' works — what target_id means per SKU category",
        "commands": [
            ("buy <sku>", "Orders to site 1 (or first VM/host) — default target"),
            ("buy <sku> <id>", "Explicit target — meaning depends on SKU category"),
            ("", ""),
            ("category: server / aipod / mainframe", "target_id = SITE id (installs a new host there)"),
            ("category: site_encryption / airfield / port / ground_station",
                "target_id = SITE id (upgrades site infrastructure)"),
            ("category: power_plant / battery_bank / fuel_storage",
                "target_id = SITE id (adds kW / kWh / fuel hours)"),
            ("category: storage_array / tape_library / cooling_unit / pump_system",
                "target_id = SITE id (adds capacity at that site)"),
            ("category: aircraft", "target_id = SITE id (needs airfield tier first)"),
            ("category: ship / submarine", "target_id = SITE id (needs port tier first)"),
            ("category: satellite", "no target — launches to orbit on the SKU's orbit"),
            ("category: vm_module", "target_id = VM id (upgrades containment component)"),
            ("category: host_module", "target_id = HOST id (in-place RAM / storage upgrade)"),
            ("", ""),
            ("examples", ""),
            ("buy generic-1u-server 2", "installs a 1U server at site 2"),
            ("buy sev-crypto-card 3", "upgrades vm 3 memory_encryption to 6"),
            ("buy host-ram-512gb 1", "adds 512 GB RAM to host 1"),
            ("buy cooling-chiller-1mw", "adds 1 MW chiller to site 1 (default)"),
            ("buy polaris-geo-comms", "launches a GEO comms sat (no site target)"),
            ("buy yacht-expedition 2", "berths a yacht at site 2 (requires port)"),
            ("", ""),
            ("tip", "run `catalog <category>` to filter — each row shows the target kind"),
        ],
    },
    "staff": {
        "title": "Staff + training + recruitment + autonomy",
        "commands": [
            ("staff", "List roster with skills, clearance, autonomy flag"),
            ("autonomy <ids> on|off", "Manual/autonomous mode.  ids: 2 | 2-5 | 1,3,7"),
            ("roles", "List hireable roles (cost, salary, lead time)"),
            ("recruit <role> [site]", "Post a requisition; hire lands at ETA"),
            ("courses", "Training courses with prereqs"),
            ("enroll <ids> <course>", "Start training.  ids: 2 | 2-5 | 1,3,7"),
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
            ("cooling", "Installed cooling units (CRAC / RDHX / chiller / DLC / immersion)"),
            ("pumps", "Installed dewatering pumps (required at underground sites)"),
            ("tapes", "Tape drives + purchased tape libraries (archive targets by site_id)"),
            ("arrays", "Storage arrays (working quarantine capacity by site_id)"),
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
        ("up", "history_prev", "history ↑"),
        ("down", "history_next", "history ↓"),
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
        # Command history (up/down arrows). Most-recent at end; idx -1 = editing new.
        self._history: list[str] = []
        self._history_idx: int = -1
        self._HISTORY_MAX = 200

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
        # Record in history (no consecutive duplicates)
        if not self._history or self._history[-1] != cmd:
            self._history.append(cmd)
            if len(self._history) > self._HISTORY_MAX:
                self._history.pop(0)
        self._history_idx = -1
        try:
            await self.execute(cmd)
        except (ConnectionError, BrokenPipeError) as exc:
            self._log(f"[yellow]daemon dropped ({exc}); attempting reconnect...[/]")
            await self._reconnect()
        except Exception as exc:
            self._log(f"[red]err: {exc}[/]")

    def action_history_prev(self) -> None:
        if not self._history:
            return
        try:
            inp = self.query_one("#cmd", Input)
        except Exception:
            return
        if self._history_idx < 0:
            self._history_idx = len(self._history) - 1
        else:
            self._history_idx = max(0, self._history_idx - 1)
        inp.value = self._history[self._history_idx]
        inp.cursor_position = len(inp.value)

    def action_history_next(self) -> None:
        try:
            inp = self.query_one("#cmd", Input)
        except Exception:
            return
        if self._history_idx < 0:
            return
        if self._history_idx >= len(self._history) - 1:
            self._history_idx = -1
            inp.value = ""
        else:
            self._history_idx += 1
            inp.value = self._history[self._history_idx]
        inp.cursor_position = len(inp.value)

    async def _maybe_cheat(self, raw_verb: str) -> bool:
        """Return True if the raw verb matches a hidden cheat code and was
        handled. Exact case-sensitive match; never surfaced in help, prefix
        resolution, or typo suggestions."""
        if raw_verb == "rainbow_dash":
            try:
                reply = await self.client.send({"type": "rainbow_dash"})
            except Exception as e:
                self._log(f"[red]cheat failed: {e}[/]")
                return True
            n = reply.get("payload", {}).get("fired", 0)
            self._log(
                f"[bold magenta]⚡ 20% cooler — flushed {n} pending event(s)[/]"
            )
            try:
                await self.refresh_recent()
                await self._show_sitrep()
                await self._refresh_statusbar()
            except Exception:
                pass
            return True
        if raw_verb == "princess_luna":
            try:
                reply = await self.client.send({"type": "princess_luna"})
            except Exception as e:
                self._log(f"[red]cheat failed: {e}[/]")
                return True
            p = reply.get("payload", {})
            self._log(
                f"[bold blue]🌙 the Princess of the Night grants +"
                f"{humanize_money(p.get('delta', 0))} → "
                f"balance {humanize_money(p.get('balance', 0))}[/]"
            )
            try:
                await self._refresh_statusbar()
            except Exception:
                pass
            return True
        return False

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

        # Check for hidden cheats BEFORE lowercasing / prefix-match, using the
        # raw typed verb for exact comparison. Nothing about these surfaces in
        # help, suggestions, or prefix resolution.
        raw_parts = cmd.split()
        raw_verb = raw_parts[0] if raw_parts else ""
        if await self._maybe_cheat(raw_verb):
            return

        parts = cmd.split()
        verb = parts[0].lower()

        # Prefix matching: if verb is a unique prefix of a known command,
        # resolve to the full name. Ambiguous prefixes surface a hint.
        resolved = self._resolve_prefix(verb)
        if resolved == "__ambiguous__":
            return  # hint already logged
        if resolved is not None and resolved != verb:
            verb = resolved

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
            # By default, hide archived — they live in the `archived` list.
            if state is None:
                items = [i for i in items if i.get("state") != "archived"]
                if not items:
                    self._log("[dim]no active items  (type 'archived' to see archives)[/]")
            elif not items:
                self._log(f"[dim]no items in state '{state}'[/]")
            for it in items:
                self._log(self._fmt_item(it))
            return

        if verb == "archived":
            # Dedicated archive browser with size + location resolution.
            # Leads with the item id so the player can grab it for
            # transfer_item / item / etc. — these ids are the canonical
            # handle, not the designation string.
            reply = await self.client.send(
                {"type": "list_items", "payload": {"state": "archived"}}
            )
            items = reply.get("payload", {}).get("items", [])
            if not items:
                self._log("[dim]no archived items[/]")
                return
            # Map site_id → name for readability
            sites_reply = await self.client.send({"type": "sitrep"})
            sites = sites_reply.get("payload", {}).get("sites", [])
            site_name = {s["id"]: s["name"] for s in sites}
            total_gb = 0.0
            self._log(f"[bold]== archive ({len(items)} items) ==[/]")
            self._log(
                "  [dim]id   designation class  H    size      location"
                "                 enc[/]"
            )
            # Sort by current_site_id then id for stable grouping
            sorted_items = sorted(
                items,
                key=lambda x: (x.get("current_site_id") or 0, x.get("id", 0)),
            )
            for it in sorted_items:
                total_gb += float(it.get("size_gb", 0) or 0)
                color = {
                    "Safe": "green", "Euclid": "yellow", "Keter": "red",
                }.get(it.get("class", ""), "white")
                loc = site_name.get(
                    it.get("current_site_id"), f"site {it.get('current_site_id')}"
                )
                enc = "🔒" if it.get("encrypted_at_rest") else "[red]!!unenc[/]"
                self._log(
                    f"  [bold cyan]{it['id']:>3}[/]  "
                    f"[{color}]{it['designation']:10s}[/] "
                    f"[{color}]{it['class']:6s}[/] "
                    f"H={it['hazard_strength']:<2} "
                    f"{it.get('size_gb', 0):>8.1f} GB  "
                    f"@{loc:<25s} {enc}"
                )
            self._log(f"  [dim]total archive size: {total_gb:,.1f} GB[/]")
            self._log(
                "  [dim]transfer: [cyan]transfer_item <id|range|list|all> "
                "<to_site> [method][/][/]"
            )
            return

        if verb == "vms":
            reply = await self.client.send({"type": "list_vms"})
            vms = reply.get("payload", {}).get("vms", [])
            if not vms:
                self._log("[dim]no vms[/]")
            for v in vms:
                self._log(self._fmt_vm(v))
            return

        if verb == "provision_vm":
            if len(parts) < 2:
                self._log("[yellow]usage: provision_vm <host_id> [name][/]")
                return
            try:
                host_id = int(parts[1])
            except ValueError:
                self._log("[red]host id must be an integer[/]")
                return
            name = parts[2] if len(parts) > 2 else None
            payload_ = {"host_id": host_id}
            if name:
                payload_["name"] = name
            reply = await self.client.send(
                {"type": "provision_vm", "payload": payload_}
            )
            if reply.get("type") == "error":
                self._log(f"[red]{reply['payload'].get('error')}[/]")
                return
            r = reply.get("payload", {})
            base = r.get("base_containment", 0)
            self._log(
                f"[green]✓ VM {r.get('vm_id')} '{r.get('name')}' on host "
                f"{r.get('host_id')}[/]  "
                f"count={r.get('vm_count')}/{r.get('max_vms')}  "
                f"base_containment=[bold]{base}[/]  "
                f"each VM now has [bold]{r.get('allocated_ram_gb')} GB[/] "
                f"of {r.get('host_ram_gb')} GB host RAM"
            )
            return

        if verb == "deprovision_vm":
            if len(parts) < 2:
                self._log("[yellow]usage: deprovision_vm <vm_id>[/]")
                return
            try:
                vm_id = int(parts[1])
            except ValueError:
                self._log("[red]vm id must be an integer[/]")
                return
            reply = await self.client.send(
                {"type": "deprovision_vm", "payload": {"vm_id": vm_id}}
            )
            if reply.get("type") == "error":
                self._log(f"[red]{reply['payload'].get('error')}[/]")
                return
            r = reply.get("payload", {})
            remaining = r.get("remaining_vms_on_host", 0)
            alloc = r.get("allocated_ram_gb_each", 0)
            if remaining:
                self._log(
                    f"[yellow]✕ VM {r.get('vm_id')} '{r.get('name')}' removed from host "
                    f"{r.get('host_id')}[/]  "
                    f"remaining_vms={remaining}  each now has [bold]{alloc} GB[/]"
                )
            else:
                self._log(
                    f"[yellow]✕ VM {r.get('vm_id')} '{r.get('name')}' removed from host "
                    f"{r.get('host_id')}[/]  [dim]host now has no VMs — "
                    f"provision_vm to use it again[/]"
                )
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
                auto = s.get("autonomy", "off")
                auto_tag = (
                    "[bold magenta]AUTO[/]" if auto == "on" else "[dim]manual[/]"
                )
                self._log(
                    f"[cyan]staff {s['id']}[/] {s['name']} "
                    f"role={s['role']} L{s['clearance']} "
                    f"[{s['status']}] {auto_tag} {is_player} [{sk}]"
                )
            return

        if verb == "autonomy":
            if len(parts) < 3 or parts[2].lower() not in ("on", "off"):
                self._log(
                    "[yellow]usage: autonomy <staff_id|range|list> on|off[/]"
                )
                return
            try:
                staff_ids = self._parse_id_range(parts[1])
            except ValueError as exc:
                self._log(f"[red]bad id range: {exc}[/]")
                return
            mode = parts[2].lower()
            if len(staff_ids) == 1:
                reply = await self.client.send(
                    {
                        "type": "set_autonomy",
                        "payload": {"staff_id": staff_ids[0], "mode": mode},
                    }
                )
                self._log_reply("autonomy", reply)
                return
            ok = 0
            failed: list[tuple[int, str]] = []
            for sid in staff_ids:
                try:
                    reply = await self.client.send(
                        {
                            "type": "set_autonomy",
                            "payload": {"staff_id": sid, "mode": mode},
                        }
                    )
                except Exception as exc:
                    failed.append((sid, str(exc)))
                    continue
                if reply.get("type") == "error":
                    failed.append((sid, reply.get("payload", {}).get("error", "?")))
                else:
                    ok += 1
            self._log(
                f"[green]batch autonomy:[/] {ok} ok / {len(staff_ids)} → {mode}"
            )
            for sid, err in failed:
                self._log(f"  [red]✗ staff {sid}:[/] {err}")
            return

        if verb == "acquire":
            if len(parts) < 2:
                self._log("[yellow]usage: acquire <item_id|range|list>[/]")
                return
            try:
                item_ids = self._parse_id_range(parts[1])
            except ValueError as exc:
                self._log(f"[red]bad id range: {exc}[/]")
                return
            if len(item_ids) == 1:
                reply = await self.client.send(
                    {"type": "acquire", "payload": {"item_id": item_ids[0]}}
                )
                self._log_reply("acquire", reply)
                return
            ok = 0
            failed: list[tuple[int, str]] = []
            for iid in item_ids:
                try:
                    reply = await self.client.send(
                        {"type": "acquire", "payload": {"item_id": iid}}
                    )
                except Exception as exc:
                    failed.append((iid, str(exc)))
                    continue
                if reply.get("type") == "error":
                    failed.append((iid, reply.get("payload", {}).get("error", "?")))
                else:
                    ok += 1
            self._log(f"[green]batch acquire:[/] {ok} ok / {len(item_ids)}")
            for iid, err in failed:
                self._log(f"  [red]✗ item {iid}:[/] {err}")
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
                self._log(
                    "[yellow]usage: archive <item_id|range|list|all> [target_site_id][/]"
                )
                return
            if parts[1].lower() == "all":
                reply_all = await self.client.send(
                    {"type": "list_items", "payload": {"state": "analyzed"}}
                )
                item_ids = [
                    i["id"]
                    for i in reply_all.get("payload", {}).get("items", [])
                ]
                if not item_ids:
                    self._log("[dim]no analyzed items to archive[/]")
                    return
            else:
                try:
                    item_ids = self._parse_id_range(parts[1])
                except ValueError as exc:
                    self._log(f"[red]bad id range: {exc}[/]")
                    return
            target_site = int(parts[2]) if len(parts) > 2 else None
            if len(item_ids) == 1:
                payload: dict = {"item_id": item_ids[0]}
                if target_site is not None:
                    payload["target_site_id"] = target_site
                reply = await self.client.send(
                    {"type": "archive", "payload": payload}
                )
                self._log_reply("archive", reply)
                return
            ok = 0
            failed: list[tuple[int, str]] = []
            for iid in item_ids:
                sub_payload: dict = {"item_id": iid}
                if target_site is not None:
                    sub_payload["target_site_id"] = target_site
                try:
                    reply = await self.client.send(
                        {"type": "archive", "payload": sub_payload}
                    )
                except Exception as exc:
                    failed.append((iid, str(exc)))
                    continue
                if reply.get("type") == "error":
                    failed.append((iid, reply.get("payload", {}).get("error", "?")))
                else:
                    ok += 1
            target_tag = (
                f" → site {target_site}" if target_site is not None else ""
            )
            self._log(f"[green]batch archive:[/] {ok} ok / {len(item_ids)}{target_tag}")
            for iid, err in failed:
                self._log(f"  [red]✗ item {iid}:[/] {err}")
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
                self._log(
                    "[yellow]usage:[/] [bold]buy <sku> [target_id][/]"
                )
                self._log(
                    "[dim]  target_id meaning depends on the SKU category:[/]\n"
                    "[dim]    server/aipod/mainframe → site id (new host lands there)[/]\n"
                    "[dim]    vm_module              → vm id (upgrades VM containment)[/]\n"
                    "[dim]    host_module            → host id (RAM/storage upgrade)[/]\n"
                    "[dim]    aircraft/ship/submarine → site id (needs airfield/port)[/]\n"
                    "[dim]    site_*/cooling/power/battery/fuel/storage/tape/pump → site id[/]\n"
                    "[dim]    satellite              → no target (launches to orbit)[/]\n"
                    "[dim]  if target_id is omitted, defaults to first site / first VM / first host[/]\n"
                    "[dim]  type [bold]help buying[/] for full examples, [bold]catalog[/] to browse, "
                    "[bold]catalog <category>[/] to filter[/]"
                )
                return
            sku = parts[1]
            payload: dict = {"sku": sku}
            if len(parts) > 2:
                target_id = int(parts[2])
                # Infer target type by SKU category (routes to the right
                # payload slot in the daemon). vm_module + host_module both
                # use target_vm_id (daemon stashes host id there); satellites
                # take no target; everything else is site-scoped.
                cat_reply = await self.client.send({"type": "catalog"})
                skus = cat_reply.get("payload", {}).get("skus", [])
                sku_info = next((x for x in skus if x["sku"] == sku), None)
                category = sku_info["category"] if sku_info else ""
                if category in ("vm_module", "host_module"):
                    payload["target_vm_id"] = target_id
                elif category == "satellite":
                    self._log(
                        "[yellow]satellites take no target_id — they launch to orbit[/]"
                    )
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
            orders_reply = await self.client.send(
                {"type": "vessel_orders", "payload": {"vessel_type": "ship", "state": "active"}}
            )
            active = {o["vessel_id"]: o for o in orders_reply.get("payload", {}).get("orders", [])}
            for s in ss:
                tag = ""
                if s["id"] in active:
                    o = active[s["id"]]
                    tag = f"  [magenta]→{o['kind']}[/] ETA {o['eta_utc'][:16]}"
                self._log(
                    f"[cyan]{s['id']:>3}[/] {s['hull_number']:8s} {s['sku']:22s} "
                    f"class={s['class']:6s} @site {s['site_id']} "
                    f"[bold]{s['status']}[/]{tag}"
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

        if verb in ("tapes", "tape_drives", "tape_libraries"):
            # Unified listing: bootstrap tape drives + purchased tape libraries.
            # Each row shows the site_id you'd use as the archive target.
            drives_reply = await self.client.send({"type": "list_tape_drives"})
            libs_reply = await self.client.send({"type": "list_tape_libraries"})
            drives = drives_reply.get("payload", {}).get("tape_drives", [])
            libs = libs_reply.get("payload", {}).get("tape_libraries", [])
            if not drives and not libs:
                self._log("[dim]no tape drives or libraries installed[/]")
                return
            if drives:
                self._log("[bold]tape drives:[/]")
                for d in drives:
                    self._log(
                        f"  [cyan]drive #{d['id']:<3}[/] {d['name']:20s} "
                        f"@site {d['site_id']}"
                    )
            if libs:
                self._log("[bold]tape libraries (purchased):[/]")
                for lb in libs:
                    cap_gb = lb["capacity_gb"]
                    if cap_gb >= 1_000_000:
                        cap_str = f"{cap_gb/1_000_000:.1f} PB"
                    else:
                        cap_str = f"{cap_gb/1_000:.0f} TB"
                    self._log(
                        f"  [cyan]library #{lb['id']:<3}[/] {lb['sku']:25s} "
                        f"{cap_str:>10}  @site {lb['site_id']}  [{lb['status']}]"
                    )
            self._log(
                "[dim]archive target any site_id above — cross-site transmission "
                "scales with link bandwidth[/]"
            )
            return

        if verb in ("arrays", "storage_arrays"):
            reply = await self.client.send({"type": "list_storage_arrays"})
            arrays = reply.get("payload", {}).get("storage_arrays", [])
            if not arrays:
                self._log("[dim]no storage arrays installed[/]")
                return
            self._log("[bold]storage arrays (working storage):[/]")
            for a in arrays:
                cap_gb = a["capacity_gb"]
                if cap_gb >= 1_000_000:
                    cap_str = f"{cap_gb/1_000_000:.1f} PB"
                else:
                    cap_str = f"{cap_gb/1_000:.0f} TB"
                self._log(
                    f"  [cyan]#{a['id']:<3}[/] {a['array_type']:6s} {cap_str:>10}  "
                    f"@site {a['site_id']}  {a['sku']:25s} [{a['status']}]"
                )
            return

        if verb == "cooling":
            reply = await self.client.send({"type": "list_cooling_units"})
            units = reply.get("payload", {}).get("cooling_units", [])
            if not units:
                self._log("[dim]no cooling units installed[/]")
            for u in units:
                self._log(
                    f"[cyan]#{u['id']:<3}[/] {u['cooling_type']:10s} "
                    f"{u['kw_rating']:>5} kW  @site {u['site_id']}  "
                    f"{u['sku']:30s} [{u['status']}]"
                )
            return

        if verb == "pumps":
            reply = await self.client.send({"type": "list_pumps"})
            pumps = reply.get("payload", {}).get("pumps", [])
            if not pumps:
                self._log("[dim]no pumps installed[/]")
            for pp in pumps:
                tag = "[green]redundant[/]" if pp["redundant"] else ""
                self._log(
                    f"[cyan]#{pp['id']:<3}[/] {pp['capacity']:6s} @site "
                    f"{pp['site_id']}  {pp['sku']:30s} [{pp['status']}] {tag}"
                )
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
            # Annotate with active order if any
            orders_reply = await self.client.send(
                {"type": "vessel_orders", "payload": {"vessel_type": "submarine", "state": "active"}}
            )
            active = {o["vessel_id"]: o for o in orders_reply.get("payload", {}).get("orders", [])}
            for s in subs:
                tag = ""
                if s["id"] in active:
                    o = active[s["id"]]
                    tag = f"  [magenta]→{o['kind']}[/] ETA {o['eta_utc'][:16]}"
                self._log(
                    f"[cyan]{s['id']:>3}[/] {s['hull_number']:8s} {s['sku']:22s} "
                    f"class={s['class']:6s} @site {s['site_id']} "
                    f"[bold]{s['status']}[/]{tag}"
                )
            return

        if verb == "vessel_equipment":
            vt = parts[1] if len(parts) > 1 else None
            vc = parts[2] if len(parts) > 2 else None
            reply = await self.client.send(
                {"type": "vessel_equipment_catalog",
                 "payload": {"vessel_type": vt, "vessel_class": vc}}
            )
            rows = reply.get("payload", {}).get("equipment", [])
            if not rows:
                self._log("[dim]no equipment matches filter[/]")
                return
            self._log(f"[bold]-- Equipment catalog ({len(rows)}) --[/]")
            for e in rows:
                fits_v = "/".join(e["fits_vessel_types"])
                fits_c = ("/".join(e["fits_classes"])) if e["fits_classes"] else "any"
                self._log(
                    f"  [cyan]{e['sku']:24s}[/] [{e['category']:11s}] "
                    f"r{e['rating']}  ${e['price_usd']:>10,}  "
                    f"{fits_v:<18s} classes={fits_c}"
                )
                self._log(f"    [dim]{e['description']}[/]")
            return

        if verb == "install_equipment":
            if len(parts) < 4:
                self._log("[yellow]usage: install_equipment <ship|sub> <id> <sku>[/]")
                return
            vt_word = parts[1].lower()
            vt = "submarine" if vt_word in ("sub", "submarine") else "ship"
            try:
                vid = int(parts[2])
            except ValueError:
                self._log("[red]vessel id must be an integer[/]")
                return
            sku = parts[3]
            reply = await self.client.send({
                "type": "install_vessel_equipment",
                "payload": {"vessel_type": vt, "vessel_id": vid, "sku": sku},
            })
            if reply.get("type") == "error":
                self._log(f"[red]{reply['payload'].get('error')}[/]")
                return
            p = reply.get("payload", {})
            self._log(
                f"[green]✓ installed[/] {sku} on {vt} {vid}  "
                f"-${p.get('price_usd', 0):,}  balance=${p.get('balance', 0):,}"
            )
            return

        if verb == "uninstall_equipment":
            if len(parts) < 2:
                self._log("[yellow]usage: uninstall_equipment <equipment_id>[/]")
                return
            try:
                eid = int(parts[1])
            except ValueError:
                self._log("[red]equipment id must be an integer[/]")
                return
            reply = await self.client.send({
                "type": "uninstall_vessel_equipment",
                "payload": {"equipment_id": eid},
            })
            if reply.get("type") == "error":
                self._log(f"[red]{reply['payload'].get('error')}[/]")
                return
            p = reply.get("payload", {})
            self._log(
                f"[green]✓ removed[/] {p.get('sku')} from {p.get('vessel_type')} "
                f"{p.get('vessel_id')}"
            )
            return

        if verb == "order":
            if len(parts) < 4:
                self._log(
                    "[yellow]usage: order <ship|sub> <id> <kind> [hours] [site_id][/]\n"
                    "[dim]  kinds: patrol (needs sensor) | escort_convoy | "
                    "standby_archive (needs pod) | return_to_port (needs site)[/]"
                )
                return
            vt_word = parts[1].lower()
            vt = "submarine" if vt_word in ("sub", "submarine") else "ship"
            try:
                vid = int(parts[2])
            except ValueError:
                self._log("[red]vessel id must be an integer[/]")
                return
            kind = parts[3]
            hours = None
            target_site = None
            if kind == "return_to_port":
                if len(parts) < 5:
                    self._log("[red]return_to_port requires a target site_id[/]")
                    return
                try:
                    target_site = int(parts[4])
                    if len(parts) > 5:
                        hours = float(parts[5])
                except ValueError:
                    self._log("[red]site_id must be an integer[/]")
                    return
            else:
                if len(parts) > 4:
                    try:
                        hours = float(parts[4])
                    except ValueError:
                        self._log("[red]hours must be numeric[/]")
                        return
            reply = await self.client.send({
                "type": "vessel_order",
                "payload": {
                    "vessel_type": vt, "vessel_id": vid, "kind": kind,
                    "hours": hours, "target_site_id": target_site,
                },
            })
            if reply.get("type") == "error":
                self._log(f"[red]{reply['payload'].get('error')}[/]")
                return
            p = reply.get("payload", {})
            self._log(
                f"[green]✓ order #{p.get('order_id')}[/] {vt} {vid} on {kind}  "
                f"payout=${p.get('payout_usd', 0):,}  ETA {p.get('eta', '?')[:16]}"
            )
            return

        if verb == "cancel_order":
            if len(parts) < 3:
                self._log("[yellow]usage: cancel_order <ship|sub> <id>[/]")
                return
            vt_word = parts[1].lower()
            vt = "submarine" if vt_word in ("sub", "submarine") else "ship"
            try:
                vid = int(parts[2])
            except ValueError:
                self._log("[red]vessel id must be an integer[/]")
                return
            reply = await self.client.send({
                "type": "cancel_vessel_order",
                "payload": {"vessel_type": vt, "vessel_id": vid},
            })
            if reply.get("type") == "error":
                self._log(f"[red]{reply['payload'].get('error')}[/]")
                return
            p = reply.get("payload", {})
            self._log(f"[yellow]✕ cancelled order #{p.get('order_id')} ({p.get('kind')})[/]")
            return

        if verb == "orders":
            reply = await self.client.send({"type": "vessel_orders", "payload": {}})
            rows = reply.get("payload", {}).get("orders", [])
            if not rows:
                self._log("[dim]no vessel orders on record[/]")
                return
            for o in rows[:30]:
                color = {
                    "active": "cyan", "complete": "green", "cancelled": "yellow"
                }.get(o["state"], "white")
                self._log(
                    f"[{color}]#{o['id']:>3}[/] {o['vessel_type']:9s} "
                    f"{o['vessel_id']:>3}  {o['kind']:16s} "
                    f"[{o['state']:9s}] payout=${o['payout_usd']:>8,} "
                    f"ETA {o['eta_utc'][:16]}"
                )
            return

        if verb == "vessel":
            if len(parts) < 3:
                self._log("[yellow]usage: vessel <ship|sub> <id>[/]")
                return
            vt_word = parts[1].lower()
            vt = "submarine" if vt_word in ("sub", "submarine") else "ship"
            try:
                vid = int(parts[2])
            except ValueError:
                self._log("[red]vessel id must be an integer[/]")
                return
            reply = await self.client.send({
                "type": "vessel_detail",
                "payload": {"vessel_type": vt, "vessel_id": vid},
            })
            if reply.get("type") == "error":
                self._log(f"[red]{reply['payload'].get('error')}[/]")
                return
            self._render_vessel_detail(reply.get("payload", {}))
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
                    "[yellow]usage: transfer_item <item_id|range|list|all> "
                    "<to_site_id> [truck|air|rail|sea|data_link][/]\n"
                    "[dim]  examples: transfer_item 5 2  |  transfer_item 3-7 2 sea  |  "
                    "transfer_item 1,3,9 2  |  transfer_item all 2 data_link[/]\n"
                    "[dim]  data_link = encrypted site-to-site transmission (no physical transit); "
                    "duration scales with bandwidth, both sites must meet the class-gated encryption floor.[/]"
                )
                return
            to_site = int(parts[2])
            if parts[1].lower() == "all":
                # 'all' = every archived item not already at the destination site
                reply_all = await self.client.send(
                    {"type": "list_items", "payload": {"state": "archived"}}
                )
                all_items = reply_all.get("payload", {}).get("items", [])
                item_ids = [
                    i["id"] for i in all_items
                    if i.get("current_site_id") != to_site
                ]
                if not item_ids:
                    self._log(
                        f"[dim]no archived items to transfer "
                        f"(all already at site {to_site})[/]"
                    )
                    return
            else:
                try:
                    item_ids = self._parse_id_range(parts[1])
                except ValueError as exc:
                    self._log(f"[red]bad id range: {exc}[/]")
                    return
            method = parts[3] if len(parts) > 3 else "truck"
            ok = 0
            failed: list[tuple[int, str]] = []
            for iid in item_ids:
                try:
                    reply = await self.client.send(
                        {
                            "type": "transfer_item",
                            "payload": {
                                "item_id": iid,
                                "to_site_id": to_site,
                                "method_id": method,
                            },
                        }
                    )
                except Exception as exc:
                    failed.append((iid, str(exc)))
                    continue
                if reply.get("type") == "error":
                    failed.append((iid, reply.get("payload", {}).get("error", "?")))
                else:
                    ok += 1
            if len(item_ids) == 1:
                # Single-item: show the detailed reply like before
                if ok:
                    self._log(f"[green]✓ transfer_item ok[/] item {item_ids[0]} → site {to_site} via {method}")
                for iid, err in failed:
                    self._log(f"[red]✗ transfer_item item {iid}:[/] {err}")
            else:
                self._log(
                    f"[green]batch transfer:[/] {ok} ok / {len(item_ids)} "
                    f"→ site {to_site} via {method}"
                )
                for iid, err in failed:
                    self._log(f"  [red]✗ item {iid}:[/] {err}")
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
                    "[yellow]usage: reassign_staff <staff_id|range|list> <to_site_id>[/]"
                )
                return
            try:
                staff_ids = self._parse_id_range(parts[1])
            except ValueError as exc:
                self._log(f"[red]bad id range: {exc}[/]")
                return
            to_site = int(parts[2])
            if len(staff_ids) == 1:
                reply = await self.client.send(
                    {
                        "type": "reassign_staff",
                        "payload": {
                            "staff_id": staff_ids[0],
                            "to_site_id": to_site,
                        },
                    }
                )
                self._log_reply("reassign_staff", reply)
                return
            ok = 0
            failed: list[tuple[int, str]] = []
            for sid in staff_ids:
                try:
                    reply = await self.client.send(
                        {
                            "type": "reassign_staff",
                            "payload": {"staff_id": sid, "to_site_id": to_site},
                        }
                    )
                except Exception as exc:
                    failed.append((sid, str(exc)))
                    continue
                if reply.get("type") == "error":
                    failed.append((sid, reply.get("payload", {}).get("error", "?")))
                else:
                    ok += 1
            self._log(
                f"[green]batch reassign:[/] {ok} ok / {len(staff_ids)} "
                f"→ site {to_site}"
            )
            for sid, err in failed:
                self._log(f"  [red]✗ staff {sid}:[/] {err}")
            return

        if verb == "security":
            # Overview of every site's rating + a one-line breakdown
            reply = await self.client.send({"type": "security_ratings"})
            rows = reply.get("payload", {}).get("ratings", [])
            if not rows:
                self._log("[dim]no sites[/]")
                return
            self._log(f"[bold]== Site security rating ({len(rows)}) ==[/]")
            self._log(
                "  [dim]id   name                     type            "
                "base  +eq  +gd  total[/]"
            )
            for r in rows:
                total = r.get("total", 0)
                color = (
                    "red" if total < 20
                    else "yellow" if total < 50
                    else "green"
                )
                self._log(
                    f"  [cyan]{r['site_id']:>3}[/]  "
                    f"{r.get('site_name', '?'):<24s} "
                    f"{r.get('site_type', '?'):<14s} "
                    f"{r.get('base', 0):>4}  {r.get('equipment_bonus', 0):>3}  "
                    f"{r.get('guard_bonus', 0):>3}  "
                    f"[{color}]{total:>5}[/]"
                )
            self._log(
                "  [dim]< 20: frequent incidents  |  20-49: occasional  |  "
                ">= 50: effectively safe[/]"
            )
            return

        if verb == "site_security":
            if len(parts) < 2:
                self._log("[yellow]usage: site_security <site_id>[/]")
                return
            try:
                sid = int(parts[1])
            except ValueError:
                self._log("[red]site id must be an integer[/]")
                return
            reply = await self.client.send(
                {"type": "site_security", "payload": {"site_id": sid}}
            )
            if reply.get("type") == "error":
                self._log(f"[red]{reply['payload'].get('error')}[/]")
                return
            p = reply.get("payload", {})
            rating = p.get("rating", {})
            total = rating.get("total", 0)
            color = "red" if total < 20 else "yellow" if total < 50 else "green"
            self._log(f"[bold]== {rating.get('site_name', '?')} "
                      f"({rating.get('site_type', '?')}) — rating [{color}]{total}[/] ==[/]")
            self._log(
                f"  base={rating.get('base', 0)}  "
                f"equipment=+{rating.get('equipment_bonus', 0)}  "
                f"guards=+{rating.get('guard_bonus', 0)}"
            )
            # Equipment
            eq = p.get("equipment", [])
            if eq:
                self._log(f"[bold]-- installed equipment ({len(eq)}) --[/]")
                for e in eq:
                    self._log(
                        f"  #{e['id']:>3}  [{e['category']:10s}] "
                        f"[cyan]{e['sku']:22s}[/] +{e['rating_bonus']:<3}  {e['name']}"
                    )
            else:
                self._log("[dim]  no security equipment installed[/]")
            # Guards
            guards = p.get("guard_contracts", [])
            if guards:
                self._log(f"[bold]-- active guard contracts ({len(guards)}) --[/]")
                for g in guards:
                    self._log(
                        f"  contract #{g['id']:>3}  {g['contract_type']:20s} "
                        f"+{g['bonus']:<3}  ${g['cost_per_period']:,}/period  "
                        f"next bill: {(g.get('next_billing_utc') or '?')[:16]}"
                    )
            else:
                self._log("[dim]  no active guard contracts[/]")
            return

        if verb == "security_catalog":
            reply = await self.client.send({"type": "security_catalog"})
            p = reply.get("payload", {})
            eq_rows = p.get("equipment", [])
            self._log(f"[bold]-- Security equipment ({len(eq_rows)}) --[/]")
            for e in eq_rows:
                blocked = (
                    " [dim](blocked on: " + ", ".join(e["blocked_site_types"]) + ")[/]"
                    if e.get("blocked_site_types") else ""
                )
                self._log(
                    f"  [cyan]{e['sku']:22s}[/] [{e['category']:10s}] "
                    f"+{e['rating_bonus']:<3} ${e['price_usd']:>9,}  {e['name']}{blocked}"
                )
                self._log(f"    [dim]{e['description']}[/]")
            guards = p.get("guard_contracts", [])
            self._log(f"[bold]-- Guard contracts ({len(guards)}) --[/]")
            for g in guards:
                per = g.get("period_seconds", 0)
                if per >= 86_400:
                    per_s = f"{per/86_400:.0f}d"
                else:
                    per_s = f"{per/3600:.0f}h"
                self._log(
                    f"  [cyan]{g['contract_type']:20s}[/] +{g['bonus']:<3} "
                    f"${g['cost_per_period']:>8,}/{per_s}  {g['name']}"
                )
                self._log(f"    [dim]{g['description']}[/]")
            return

        if verb == "install_security":
            if len(parts) < 3:
                self._log("[yellow]usage: install_security <site_id> <sku>[/]")
                return
            try:
                sid = int(parts[1])
            except ValueError:
                self._log("[red]site id must be an integer[/]")
                return
            sku = parts[2]
            reply = await self.client.send({
                "type": "install_security",
                "payload": {"site_id": sid, "sku": sku},
            })
            if reply.get("type") == "error":
                self._log(f"[red]{reply['payload'].get('error')}[/]")
                return
            r = reply.get("payload", {})
            self._log(
                f"[green]✓ installed[/] {sku} on site {sid}  "
                f"+{r.get('rating_bonus', 0)} rating  "
                f"-${r.get('price_usd', 0):,}  balance=${r.get('balance', 0):,}"
            )
            return

        if verb == "uninstall_security":
            if len(parts) < 2:
                self._log("[yellow]usage: uninstall_security <equipment_id>[/]")
                return
            try:
                eid = int(parts[1])
            except ValueError:
                self._log("[red]equipment id must be an integer[/]")
                return
            reply = await self.client.send({
                "type": "uninstall_security",
                "payload": {"equipment_id": eid},
            })
            if reply.get("type") == "error":
                self._log(f"[red]{reply['payload'].get('error')}[/]")
                return
            r = reply.get("payload", {})
            self._log(
                f"[yellow]✕ removed[/] {r.get('sku')} from site {r.get('site_id')}"
            )
            return

        if verb == "hire_guards":
            if len(parts) < 3:
                self._log(
                    "[yellow]usage: hire_guards <site_id> "
                    "<guard_watch_single|guard_watch_shift|pmsc_team_light|pmsc_team_heavy|mtf_squad>[/]"
                )
                return
            try:
                sid = int(parts[1])
            except ValueError:
                self._log("[red]site id must be an integer[/]")
                return
            tier = parts[2]
            reply = await self.client.send({
                "type": "hire_guards",
                "payload": {"site_id": sid, "contract_type": tier},
            })
            if reply.get("type") == "error":
                self._log(f"[red]{reply['payload'].get('error')}[/]")
                return
            r = reply.get("payload", {})
            self._log(
                f"[green]✓ guard contract #{r.get('contract_id')}[/] "
                f"{tier} active on site {sid}  "
                f"next bill: {r.get('next_billing', '?')[:16]}  "
                f"balance=${r.get('balance', 0):,}"
            )
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

        if verb == "roles":
            reply = await self.client.send({"type": "roles"})
            roles = reply.get("payload", {}).get("roles", [])
            for r in roles:
                lead = r.get("lead_time_s", 0)
                if lead < 86_400:
                    lead_s = f"{lead/3600:.0f}h"
                else:
                    lead_s = f"{lead/86_400:.0f}d"
                skills = " ".join(f"{k}={v}" for k, v in r.get("skills", {}).items())
                self._log(
                    f"[cyan]{r['role_id']:22s}[/] {r['display_name']:30s} "
                    f"{humanize_money(r['recruit_cost_usd']):>8} "
                    f"+ {humanize_money(r['annual_salary_usd']):>8}/yr  "
                    f"lead={lead_s:<4}  L{r['clearance']}  [{skills}]"
                )
            return

        if verb == "recruit":
            if len(parts) < 2:
                self._log("[yellow]usage: recruit <role_id> [site_id][/]")
                return
            recruit_payload: dict = {"role_id": parts[1]}
            if len(parts) > 2:
                recruit_payload["target_site_id"] = int(parts[2])
            reply = await self.client.send(
                {"type": "recruit", "payload": recruit_payload}
            )
            self._log_reply("recruit", reply)
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
                self._log(
                    "[yellow]usage: enroll <staff_id|range|list> <course_id>[/]"
                )
                return
            try:
                staff_ids = self._parse_id_range(parts[1])
            except ValueError as exc:
                self._log(f"[red]bad id range: {exc}[/]")
                return
            course = parts[2]
            if len(staff_ids) == 1:
                reply = await self.client.send(
                    {
                        "type": "enroll",
                        "payload": {
                            "staff_id": staff_ids[0],
                            "course_id": course,
                        },
                    }
                )
                self._log_reply("enroll", reply)
                return
            ok = 0
            failed: list[tuple[int, str]] = []
            for sid in staff_ids:
                try:
                    reply = await self.client.send(
                        {
                            "type": "enroll",
                            "payload": {"staff_id": sid, "course_id": course},
                        }
                    )
                except Exception as exc:
                    failed.append((sid, str(exc)))
                    continue
                if reply.get("type") == "error":
                    failed.append((sid, reply.get("payload", {}).get("error", "?")))
                else:
                    ok += 1
            self._log(
                f"[green]batch enroll:[/] {ok} ok / {len(staff_ids)} "
                f"→ {course}"
            )
            for sid, err in failed:
                self._log(f"  [red]✗ staff {sid}:[/] {err}")
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

        if verb == "site":
            if len(parts) < 2:
                self._log("[yellow]usage: site <site_id>[/]")
                return
            try:
                site_id = int(parts[1])
            except ValueError:
                self._log("[red]site id must be an integer[/]")
                return
            reply = await self.client.send(
                {"type": "site_detail", "payload": {"site_id": site_id}}
            )
            if reply.get("type") == "error":
                self._log(f"[red]{reply['payload'].get('error')}[/]")
                return
            self._render_site_detail(reply.get("payload", {}))
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

    @staticmethod
    def _parse_id_range(arg: str) -> list[int]:
        """Parse id arg: '5' / '3-7' / '1,3,5' / '1-3,7,10-12'. Returns a
        de-duplicated list of ints preserving order. Raises ValueError on
        malformed input."""
        ids: list[int] = []
        seen: set[int] = set()
        arg = arg.strip()
        if not arg:
            raise ValueError("empty id range")
        for chunk in arg.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if "-" in chunk and not chunk.startswith("-"):
                lo_s, hi_s = chunk.split("-", 1)
                lo, hi = int(lo_s), int(hi_s)
                if lo > hi:
                    lo, hi = hi, lo
                for n in range(lo, hi + 1):
                    if n not in seen:
                        ids.append(n)
                        seen.add(n)
            else:
                n = int(chunk)
                if n not in seen:
                    ids.append(n)
                    seen.add(n)
        return ids

    def _all_known_verbs(self) -> list[str]:
        if self._known_verbs:
            return self._known_verbs
        verbs: set[str] = {"quit", "exit", "help"}
        for topic in HELP_TOPICS.values():
            for cmd, _desc in topic["commands"]:
                tokens = cmd.split()
                if not tokens:
                    continue   # blank divider row inside help
                first = tokens[0]
                # Skip documentation markers ("category:", "examples", "tip")
                # — they are section labels, not invokable verbs.
                if first.endswith(":") or first in {"examples", "tip"}:
                    continue
                verbs.add(first)
        verbs.update({"item", "vm", "host"})   # detail views not in help topics
        self._known_verbs = sorted(verbs)
        return self._known_verbs

    def _resolve_prefix(self, verb: str) -> str | None:
        """Return the full command name if `verb` is a unique prefix match.
        If ambiguous, log the options and return None to fall through.
        Exact matches return themselves unchanged."""
        if not verb or len(verb) < 2:
            return None
        known = self._all_known_verbs()
        if verb in known:
            return verb
        matches = [v for v in known if v.startswith(verb)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            self._log(
                f"[yellow]'{verb}' is ambiguous:[/] "
                f"{', '.join(matches)}  [dim](type more letters)[/]"
            )
            # Signal caller to NOT run the unknown verb
            return "__ambiguous__"
        return None

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
        size = it.get("size_gb", 0)
        enc = it.get("encrypted_at_rest", False)
        enc_tag = "[green]encrypted-at-rest[/]" if enc else "[red]UNENCRYPTED at rest[/]"
        self._log(f"  payload: {size:.1f} GB  {enc_tag}")
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

    def _render_vessel_detail(self, d: dict) -> None:
        """Full dashboard for one ship or submarine."""
        v = d.get("vessel") or {}
        vt = d.get("vessel_type", "vessel")
        self._log(f"[bold]{'=' * 62}[/]")
        label = "SHIP" if vt == "ship" else "SUBMARINE"
        self._log(
            f"[bold cyan]{label} {v.get('id')}[/]  {v.get('hull_number')}  "
            f"[dim]sku={v.get('sku')} class={v.get('class')} "
            f"@site {v.get('site_id')} [{v.get('status')}][/]"
        )
        # Ratings
        self._log(
            f"  sensor_rating={d.get('sensor_rating', 0)}  "
            f"stealth_rating={d.get('stealth_rating', 0)}  "
            f"archive_cap={d.get('archive_cap_gb', 0):,} GB"
        )

        # Active order
        active = d.get("active_order")
        if active:
            self._log(
                f"[bold]-- active order --[/]\n"
                f"  #{active['id']} {active['kind']:16s} "
                f"payout=${active['payout_usd']:,}  ETA {active['eta_utc'][:16]}"
            )
        else:
            self._log("[dim]  no active order[/]")

        # Equipment
        equip = d.get("equipment", [])
        if equip:
            self._log(f"[bold]-- equipment ({len(equip)}) --[/]")
            for e in equip:
                self._log(
                    f"  #{e['id']:>3} [{e['category']:11s}] "
                    f"[cyan]{e['sku']:24s}[/] r{e['rating']}  {e['name']}"
                )
        else:
            self._log("[dim]  no equipment installed[/]")

        # Recent orders
        recent = d.get("recent_orders", [])
        if recent:
            self._log(f"[bold]-- recent orders ({len(recent)}) --[/]")
            for o in recent:
                color = {
                    "active": "cyan", "complete": "green", "cancelled": "yellow"
                }.get(o["state"], "white")
                self._log(
                    f"  [{color}]#{o['id']:>3}[/] {o['kind']:16s} "
                    f"[{o['state']:9s}] payout=${o['payout_usd']:,}"
                )
        self._log(f"[bold]{'=' * 62}[/]")

    def _render_site_detail(self, d: dict) -> None:
        """Full dashboard for one site — everything in one place."""
        site = d.get("site") or {}
        u = d.get("utilization") or {}
        self._log(f"[bold]{'=' * 62}[/]")
        self._log(
            f"[bold cyan]SITE {site.get('id')}[/]  {site.get('name')}  "
            f"[dim]type={site.get('type')} created={site.get('created_at', '')[:10]}[/]"
        )
        # Connectivity + encryption
        net = d.get("network_tier") or "?"
        enc = d.get("encryption_level") or "none"
        enc_color = {"none": "red", "software": "yellow",
                     "hardware": "green", "type1": "bold green"}.get(enc, "white")
        self._log(
            f"  network=[cyan]{net}[/]  encryption=[{enc_color}]{enc}[/]  "
            f"airfield={d.get('airfield_tier')}  port={d.get('port_tier')}  "
            f"ground_station={d.get('ground_station_tier')}"
        )
        # Power + cooling + resilience
        pw_col = "red" if u.get("power_over") else "green"
        cl_col = "red" if u.get("cooling_over") else "green"
        res = d.get("resilience", {})
        tags = []
        if u.get("fuel_starved"):
            tags.append("[bold red]FUEL-STARVED[/]")
        if u.get("flooded"):
            tags.append("[bold red]FLOODED[/]")
        if u.get("outaged"):
            tags.append("[bold red]GRID-DARK[/]")
        tag_str = "  " + " ".join(tags) if tags else ""
        self._log(
            f"  power=[{pw_col}]{u.get('power_kw_used', 0):.2f}/"
            f"{u.get('power_kw_capacity', 0)}kW[/] "
            f"(nominal {u.get('power_kw_nominal', 0)}, plants {u.get('power_kw_plants', 0)})  "
            f"cooling=[{cl_col}]{u.get('cooling_kw_used', 0):.2f}/"
            f"{u.get('cooling_kw_capacity', 0)}kW[/]{tag_str}"
        )
        self._log(
            f"  resilience: battery={res.get('battery_kwh', 0):.0f} kWh  "
            f"fuel={res.get('fuel_hours', 0):.0f} h  "
            f"→ ride≈{u.get('ride_through_hours', 0):.1f} h"
        )
        # Security rating
        sec = d.get("security") or {}
        sec_total = sec.get("total", 0)
        sec_col = (
            "red" if sec_total < 20
            else "yellow" if sec_total < 50 else "green"
        )
        self._log(
            f"  security: [{sec_col}]{sec_total}[/]  "
            f"(base {sec.get('base', 0)} + eq {sec.get('equipment_bonus', 0)} "
            f"+ guards {sec.get('guard_bonus', 0)})  "
            f"[dim]< 20 = frequent incidents | ≥ 50 = safe[/]"
        )
        # Storage / tape / ram
        stor_col = "red" if u.get("storage_over") else "green"
        tape_col = "red" if u.get("tape_over") else "green"
        self._log(
            f"  storage=[{stor_col}]{u.get('storage_used_gb', 0):.0f}/"
            f"{u.get('storage_cap_gb', 0):.0f} GB[/]  "
            f"tape=[{tape_col}]{u.get('tape_used_gb', 0):.0f}/"
            f"{u.get('tape_cap_gb', 0):.0f} GB[/]  "
            f"RAM={u.get('ram_cap_gb', 0)} GB"
        )

        # Active outages
        outs = d.get("active_outages", [])
        if outs:
            self._log(f"  [bold red]ACTIVE OUTAGES:[/] {len(outs)}")
            for o in outs:
                ride = "ride-through" if o["ride_through"] else "[red]DARK[/]"
                self._log(
                    f"    #{o['id']} {o['kind']} {o['duration_h']:.1f}h {ride}"
                )

        # Staff
        staff = d.get("staff", [])
        if staff:
            self._log(f"[bold]-- staff ({len(staff)}) --[/]")
            for s in staff:
                auto = "[bold magenta]AUTO[/]" if s.get("autonomy") == "on" else "manual"
                you = "[bold green](you)[/]" if s.get("is_player") else ""
                sk = " ".join(f"{k}={v}" for k, v in s.get("skills", {}).items())
                self._log(
                    f"  {s['id']:>3}  {s['name']:24s} {s['role']:18s} "
                    f"L{s['clearance']}  [{s['status']}]  {auto}  {you}  [dim]{sk}[/]"
                )

        # Hosts + VMs
        hosts = d.get("hosts", [])
        vms = d.get("vms", [])
        if hosts:
            self._log(f"[bold]-- compute ({len(hosts)} hosts, {len(vms)} VMs) --[/]")
            for h in hosts:
                specs = h.get("specs", {})
                self._log(
                    f"  host {h['id']:>3}  {h['name']:26s} {h['class']:10s} "
                    f"[{h['status']}]  "
                    f"ram={specs.get('ram_gb', 0)}GB storage={specs.get('storage_gb', 0)}GB "
                    f"power={specs.get('power_w', 0)}W"
                )
                for v in vms:
                    if v["host_id"] == h["id"]:
                        cont = sum(int(x) for x in v.get("spec", {}).values())
                        self._log(
                            f"    vm {v['id']:>3}  {v['name']:20s} containment={cont}  "
                            f"[{v['status']}]"
                        )

        # Items on this site
        ibs = d.get("items_by_state", {})
        active = sum(len(ibs.get(s, [])) for s in
                     ("candidate", "quarantined", "analyzing", "analyzed",
                      "archiving", "in_transit"))
        archived_list = ibs.get("archived", [])
        archived = len(archived_list)
        if active or archived:
            self._log(f"[bold]-- items --[/]")
            for state in ("candidate", "quarantined", "analyzing", "analyzed",
                          "archiving", "in_transit"):
                xs = ibs.get(state, [])
                if xs:
                    # Show id:designation so the player can act on them
                    # (analyze, archive, etc.) without a second lookup.
                    shown = ", ".join(
                        f"#{i['id']}:{i['designation']}({i['class'][0]})"
                        for i in xs[:8]
                    )
                    suffix = "..." if len(xs) > 8 else ""
                    self._log(f"  {state:12s}: {len(xs)}  {shown}{suffix}")
            if archived:
                self._log(f"  [bold]archived[/]    : {archived}")
                # Show archived item ids inline (up to 20) — these are
                # the handles the player needs for transfer_item.
                preview = archived_list[:20]
                color_by_class = {"Safe": "green", "Euclid": "yellow", "Keter": "red"}
                for it in preview:
                    c = color_by_class.get(it.get("class", ""), "white")
                    self._log(
                        f"    [bold cyan]{it['id']:>3}[/]  "
                        f"[{c}]{it['designation']:10s}[/] [{c}]{it['class']:6s}[/] "
                        f"H={it['hazard_strength']:<2} "
                        f"{it.get('size_gb', 0):>7.1f} GB"
                    )
                if archived > 20:
                    self._log(
                        f"    [dim]... +{archived - 20} more; "
                        f"run 'archived' for full list[/]"
                    )

        # Infrastructure additions
        def _section(title, rows, render):
            if rows:
                self._log(f"[bold]-- {title} ({len(rows)}) --[/]")
                for r in rows:
                    self._log(f"  {render(r)}")
        _section("power plants", d.get("power_plants", []),
                 lambda p: f"{p['plant_type']:12s} {p['kw_rating']:>5} kW  {p['sku']:30s} [{p['status']}]")
        _section("cooling units", d.get("cooling_units", []),
                 lambda c: f"{c['cooling_type']:10s} {c['kw_rating']:>5} kW  {c['sku']:30s} [{c['status']}]")
        _section("pumps", d.get("pumps", []),
                 lambda p: f"{p['capacity']:6s} {p['sku']:30s} [{p['status']}]")
        _section("storage arrays", d.get("storage_arrays", []),
                 lambda a: f"{a['array_type']:6s} {a['capacity_gb']:>10,.0f} GB  {a['sku']:25s} [{a['status']}]")
        _section("tape drives", d.get("tape_drives", []),
                 lambda t: f"{t.get('name', '')}")
        _section("tape libraries", d.get("tape_libraries", []),
                 lambda t: f"{t['capacity_gb']:>12,.0f} GB  {t['sku']:25s} [{t['status']}]")

        # Fleet based here
        fleet = d.get("aircraft", []) + d.get("ships", []) + d.get("submarines", [])
        if fleet:
            if d.get("aircraft"):
                _section("aircraft", d["aircraft"],
                         lambda a: f"{a['tail_number']:8s} {a['sku']:22s} class={a['class']:18s} [{a['status']}]")
            if d.get("ships"):
                _section("ships", d["ships"],
                         lambda s: f"{s['hull_number']:8s} {s['sku']:22s} class={s['class']:10s} [{s['status']}]")
            if d.get("submarines"):
                _section("submarines", d["submarines"],
                         lambda s: f"{s['hull_number']:8s} {s['sku']:22s} class={s['class']:10s} [{s['status']}]")

        self._log(f"[bold]{'=' * 62}[/]")

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
        if kind == "hire_complete":
            return (
                f"{payload.get('name')} as {payload.get('role_id')} "
                f"(${payload.get('annual_salary', 0):,}/yr)"
            )
        if kind == "payroll_run":
            return (
                f"${payload.get('weekly_total', 0):,} across "
                f"{payload.get('staff_paid', 0)} staff"
            )
        if kind == "recruitment_ordered":
            return (
                f"{payload.get('candidate_name')} ({payload.get('role_id')}) "
                f"-${payload.get('recruit_cost', 0):,}"
            )
        if kind == "agent_action":
            name = payload.get("staff_name", "?")
            act = payload.get("action", "?")
            target_bits = []
            if payload.get("item_id") is not None:
                target_bits.append(f"item {payload['item_id']}")
            if payload.get("vm_id") is not None:
                target_bits.append(f"vm {payload['vm_id']}")
            if payload.get("host_id") is not None:
                target_bits.append(f"host {payload['host_id']}")
            tail = f" {' '.join(target_bits)}" if target_bits else ""
            return f"{name} → {act}{tail}"
        if kind == "staff_agent_tick":
            return ""
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
            src = p.get("source_site_id")
            dst = p.get("target_site_id")
            route = (
                f"same-site"
                if src == dst
                else f"site {src} → site {dst} ({p.get('size_gb', 0):.1f} GB)"
            )
            return (
                f"archiving {route}... ETA {humanize_eta(p.get('eta'))}  "
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
        if verb == "recruit":
            return (
                f"candidate {p.get('candidate_name')} ({p.get('role_id')}) — "
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

    # Category → what target_id refers to when buying this SKU.
    _TARGET_BY_CATEGORY: dict[str, str] = {
        "server": "site",
        "aipod": "site",
        "mainframe": "site",
        "site_encryption": "site",
        "airfield": "site",
        "port": "site",
        "ground_station": "site",
        "power_plant": "site",
        "battery_bank": "site",
        "fuel_storage": "site",
        "storage_array": "site",
        "tape_library": "site",
        "cooling_unit": "site",
        "pump_system": "site",
        "aircraft": "site",
        "ship": "site",
        "submarine": "site",
        "vm_module": "vm",
        "host_module": "host",
        "satellite": "orbit",
    }

    @classmethod
    def _target_kind(cls, category: str) -> str:
        return cls._TARGET_BY_CATEGORY.get(category, "site")

    @classmethod
    def _fmt_sku(cls, s: dict) -> str:
        cat_color = {
            "server": "cyan",
            "aipod": "magenta",
            "mainframe": "bold magenta",
            "vm_module": "yellow",
            "host_module": "yellow",
            "satellite": "bold cyan",
            "aircraft": "green",
            "ship": "green",
            "submarine": "green",
            "cooling_unit": "blue",
            "power_plant": "red",
            "storage_array": "white",
            "tape_library": "white",
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
        target = cls._target_kind(s.get("category", ""))
        return (
            f"[{cat_color}]{s['category']:15s}[/] {s['sku']:25s} "
            f"${s['price_usd']:>10,}  {s['power_w']:>5}W  lead={lead_str:<4}  "
            f"[dim](target:{target})[/]  "
            f"[dim]{s.get('description', '')}[/]"
        )

    @staticmethod
    def _fmt_vm(v: dict) -> str:
        spec = v.get("spec", {})
        containment = sum(int(x) for x in spec.values())
        alloc = v.get("allocated_ram_gb")
        host_ram = v.get("host_ram_gb")
        ram_tag = ""
        if alloc is not None and host_ram:
            sibs = v.get("siblings_on_host", 1)
            ram_tag = f" ram={alloc}/{host_ram}GB (÷{sibs})"
        return (
            f"[cyan]vm[/] id={v['id']} {v['name']} on host {v['host_id']} "
            f"containment={containment}{ram_tag} status=[bold]{v['status']}[/] "
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
            if u.get("flooded"):
                fuel_tag += " [bold red]FLOODED (no pumps)[/]"
            ride_h = u.get("ride_through_hours", 0)
            ride_tag = (
                f"  ride≈{ride_h:.0f}h"
                if ride_h > 0 else ""
            )
            stor_color = "red" if u.get("storage_over") else "green"
            tape_color = "red" if u.get("tape_over") else "green"
            stor_used = u.get("storage_used_gb", 0)
            stor_cap = u.get("storage_cap_gb", 0)
            tape_used = u.get("tape_used_gb", 0)
            tape_cap = u.get("tape_cap_gb", 0)
            self._log(
                f"  [cyan]site {u['site_id']}[/] hosts={u['hosts']}  "
                f"power=[{pw_color}]{u['power_kw_used']:.2f}/"
                f"{u['power_kw_capacity']}kW[/]  "
                f"cooling=[{cl_color}]{u['cooling_kw_used']:.2f}/"
                f"{u['cooling_kw_capacity']}kW[/]  "
                f"net=[dim]{net.get('tier', '?')}[/]  "
                f"enc=[{enc_color}]{enc}[/]{ride_tag}{fuel_tag}"
            )
            self._log(
                f"    storage=[{stor_color}]{stor_used:.0f}/{stor_cap:.0f}GB[/]  "
                f"tape=[{tape_color}]{tape_used:.0f}/{tape_cap:.0f}GB[/]  "
                f"RAM={u.get('ram_cap_gb', 0)}GB"
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
