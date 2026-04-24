from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .clock import iso, now_utc


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc    TEXT NOT NULL,
    kind      TEXT NOT NULL,
    severity  TEXT NOT NULL,
    payload   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts_utc);

CREATE TABLE IF NOT EXISTS scheduled (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    eta_utc   TEXT NOT NULL,
    kind      TEXT NOT NULL,
    payload   TEXT NOT NULL,
    fired     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_scheduled_pending ON scheduled(eta_utc) WHERE fired = 0;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sites (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    site_type   TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hosts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id     INTEGER NOT NULL,
    name        TEXT NOT NULL,
    host_class  TEXT NOT NULL,
    specs       TEXT NOT NULL,
    status      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vms (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    host_id     INTEGER NOT NULL,
    name        TEXT NOT NULL,
    spec        TEXT NOT NULL,
    status      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tape_drives (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id     INTEGER NOT NULL,
    name        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    designation     TEXT NOT NULL,
    item_class      TEXT NOT NULL,
    hazard_strength INTEGER NOT NULL,
    profile         TEXT NOT NULL,
    state           TEXT NOT NULL,
    current_vm_id   INTEGER,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS funding (
    id       INTEGER PRIMARY KEY CHECK (id = 1),
    balance  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS staff (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    role             TEXT NOT NULL,
    is_player        INTEGER NOT NULL DEFAULT 0,
    skills           TEXT NOT NULL,
    clearance        INTEGER NOT NULL,
    status           TEXT NOT NULL,
    assigned_site_id INTEGER,
    salary           INTEGER NOT NULL,
    hired_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mistakes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc       TEXT NOT NULL,
    kind         TEXT NOT NULL,
    action       TEXT NOT NULL,
    operator_id  INTEGER,
    item_id      INTEGER,
    host_id      INTEGER,
    vm_id        INTEGER,
    overridden   INTEGER NOT NULL DEFAULT 0,
    details      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mistakes_ts ON mistakes(ts_utc);

CREATE TABLE IF NOT EXISTS incidents (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc        TEXT NOT NULL,
    severity      TEXT NOT NULL,
    item_id       INTEGER,
    host_id       INTEGER,
    vm_id         INTEGER,
    operator_id   INTEGER,
    vector        TEXT NOT NULL,
    root_cause    TEXT NOT NULL,
    contributing  TEXT NOT NULL,
    exposure      TEXT NOT NULL,
    recommend     TEXT NOT NULL,
    mistake_ids   TEXT NOT NULL,
    report        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_incidents_ts ON incidents(ts_utc);

CREATE TABLE IF NOT EXISTS site_capacity (
    site_id    INTEGER PRIMARY KEY,
    power_kw   INTEGER NOT NULL,
    cooling_kw INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS purchases (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sku             TEXT NOT NULL,
    price_usd       INTEGER NOT NULL,
    status          TEXT NOT NULL,            -- ordered | installed
    target_site_id  INTEGER,
    target_vm_id    INTEGER,
    ordered_at      TEXT NOT NULL,
    eta_utc         TEXT NOT NULL,
    installed_at    TEXT
);

CREATE TABLE IF NOT EXISTS enrollments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_id      INTEGER NOT NULL,
    course_id     TEXT NOT NULL,
    status        TEXT NOT NULL,              -- enrolled | graduated | cancelled
    enrolled_at   TEXT NOT NULL,
    eta_utc       TEXT NOT NULL,
    completed_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_enrollments_staff ON enrollments(staff_id);

CREATE TABLE IF NOT EXISTS site_network (
    site_id INTEGER PRIMARY KEY,
    tier    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS site_encryption (
    site_id      INTEGER PRIMARY KEY,
    level        TEXT NOT NULL,    -- none | software | hardware | type1
    installed_at TEXT
);

CREATE TABLE IF NOT EXISTS playbooks (
    site_id  INTEGER PRIMARY KEY,
    rules    TEXT NOT NULL        -- json: {rule_name: bool}
);

CREATE TABLE IF NOT EXISTS site_airfield (
    site_id INTEGER PRIMARY KEY,
    tier    TEXT NOT NULL        -- none | dirt_strip | small_airport | private_airfield
);

CREATE TABLE IF NOT EXISTS aircraft (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id        INTEGER NOT NULL,
    tail_number    TEXT NOT NULL,
    sku            TEXT NOT NULL,
    aircraft_class TEXT NOT NULL,
    status         TEXT NOT NULL,   -- parked | in_flight | maintenance
    purchased_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_aircraft_site ON aircraft(site_id);

CREATE TABLE IF NOT EXISTS site_port (
    site_id INTEGER PRIMARY KEY,
    tier    TEXT NOT NULL        -- none | small_port | deepwater_port
);

CREATE TABLE IF NOT EXISTS ships (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id        INTEGER NOT NULL,
    hull_number    TEXT NOT NULL,
    sku            TEXT NOT NULL,
    ship_class     TEXT NOT NULL,
    status         TEXT NOT NULL,   -- berthed | at_sea | maintenance
    purchased_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ships_site ON ships(site_id);

CREATE TABLE IF NOT EXISTS satellites (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    callsign        TEXT NOT NULL,
    sku             TEXT NOT NULL,
    satellite_class TEXT NOT NULL,       -- cubesat | smallsat | largesat
    orbit           TEXT NOT NULL,       -- LEO | SSO | MEO | GEO | HEO
    payload         TEXT NOT NULL,       -- comms | storage | compute | imint | sigint
    status          TEXT NOT NULL,       -- on_orbit | commissioning | defunct
    launched_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS site_ground_station (
    site_id INTEGER PRIMARY KEY,
    tier    TEXT NOT NULL    -- none | portable | fixed_small | fixed_medium | deep_space | phased_array
);

CREATE TABLE IF NOT EXISTS submarines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id         INTEGER NOT NULL,
    hull_number     TEXT NOT NULL,
    sku             TEXT NOT NULL,
    sub_class       TEXT NOT NULL,       -- uuv | xluuv | ssk | ssn | ssbn
    status          TEXT NOT NULL,       -- berthed | submerged | refit
    purchased_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_submarines_site ON submarines(site_id);

CREATE TABLE IF NOT EXISTS power_plants (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id         INTEGER NOT NULL,
    sku             TEXT NOT NULL,
    plant_type      TEXT NOT NULL,       -- genset | solar | microreactor | smr
    kw_rating       INTEGER NOT NULL,
    status          TEXT NOT NULL,       -- online | offline | maintenance
    installed_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_power_plants_site ON power_plants(site_id);

CREATE TABLE IF NOT EXISTS site_resilience (
    site_id       INTEGER PRIMARY KEY,
    battery_kwh   REAL NOT NULL DEFAULT 0,
    fuel_hours    REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS outages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id         INTEGER NOT NULL,
    kind            TEXT NOT NULL,      -- grid_power | isp
    duration_h      REAL NOT NULL,
    ride_through    INTEGER NOT NULL,   -- 0/1
    started_at      TEXT NOT NULL,
    eta_end_utc     TEXT NOT NULL,
    status          TEXT NOT NULL       -- active | resolved
);
CREATE INDEX IF NOT EXISTS idx_outages_active ON outages(site_id, status);

CREATE TABLE IF NOT EXISTS storage_arrays (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id         INTEGER NOT NULL,
    sku             TEXT NOT NULL,
    capacity_gb     REAL NOT NULL,
    array_type      TEXT NOT NULL,   -- ssd | hdd | hybrid
    status          TEXT NOT NULL,   -- online | offline
    installed_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_storage_arrays_site ON storage_arrays(site_id);

CREATE TABLE IF NOT EXISTS tape_libraries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id         INTEGER NOT NULL,
    sku             TEXT NOT NULL,
    capacity_gb     REAL NOT NULL,
    status          TEXT NOT NULL,
    installed_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tape_libraries_site ON tape_libraries(site_id);

CREATE TABLE IF NOT EXISTS pumps (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id         INTEGER NOT NULL,
    sku             TEXT NOT NULL,
    capacity        TEXT NOT NULL,     -- small | large
    redundant       INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL,     -- online | offline | maintenance
    installed_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pumps_site ON pumps(site_id);

CREATE TABLE IF NOT EXISTS cooling_units (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id         INTEGER NOT NULL,
    sku             TEXT NOT NULL,
    kw_rating       INTEGER NOT NULL,
    cooling_type    TEXT NOT NULL,     -- crac | rdhx | chiller | dlc | immersion
    status          TEXT NOT NULL,     -- online | offline | maintenance
    installed_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cooling_site ON cooling_units(site_id);

CREATE TABLE IF NOT EXISTS contracts (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_type          TEXT NOT NULL,
    target_site_id         INTEGER,
    target_vm_id           INTEGER,
    cost_per_period        INTEGER NOT NULL,
    period_seconds         REAL NOT NULL,
    status                 TEXT NOT NULL,          -- active | lapsed | cancelled
    details                TEXT NOT NULL,          -- json
    started_at             TEXT NOT NULL,
    next_billing_utc       TEXT,
    last_billed_utc        TEXT
);
CREATE INDEX IF NOT EXISTS idx_contracts_status ON contracts(status);

CREATE TABLE IF NOT EXISTS vessel_equipment (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    vessel_type   TEXT NOT NULL,       -- 'ship' | 'submarine'
    vessel_id     INTEGER NOT NULL,
    sku           TEXT NOT NULL,
    installed_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vessel_equipment_vessel
    ON vessel_equipment(vessel_type, vessel_id);

CREATE TABLE IF NOT EXISTS vessel_orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    vessel_type   TEXT NOT NULL,
    vessel_id     INTEGER NOT NULL,
    kind          TEXT NOT NULL,
    params_json   TEXT NOT NULL,
    state         TEXT NOT NULL,       -- 'active' | 'complete' | 'cancelled'
    started_at    TEXT NOT NULL,
    eta_utc       TEXT NOT NULL,
    payout_usd    INTEGER NOT NULL DEFAULT 0,
    scheduled_id  INTEGER,
    effect_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_vessel_orders_state
    ON vessel_orders(state);
CREATE INDEX IF NOT EXISTS idx_vessel_orders_vessel
    ON vessel_orders(vessel_type, vessel_id, state);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS site_security_equipment (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id       INTEGER NOT NULL,
    sku           TEXT NOT NULL,
    installed_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_site_security_site
    ON site_security_equipment(site_id);
"""


class Journal:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), isolation_level=None)
        self._conn.executescript(SCHEMA)
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        # Forward-compat column adds — cheap on existing DBs, no-op after first run.
        self._ensure_column("items", "current_site_id", "INTEGER")
        self._ensure_column("items", "transit_to_site_id", "INTEGER")
        self._ensure_column("items", "size_gb", "REAL DEFAULT 0")
        self._ensure_column("items", "encrypted_at_rest", "INTEGER DEFAULT 0")
        self._ensure_column("hosts", "transit_to_site_id", "INTEGER")
        self._ensure_column("staff", "transit_to_site_id", "INTEGER")
        self._ensure_column("staff", "autonomy", "TEXT DEFAULT 'off'")

    def _ensure_column(self, table: str, column: str, sqltype: str) -> None:
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        cols = {r[1] for r in rows}
        if column not in cols:
            self._conn.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {sqltype}"
            )

    # --- event log -----------------------------------------------------

    def append(self, kind: str, severity: str, payload: dict) -> int:
        cur = self._conn.execute(
            "INSERT INTO events (ts_utc, kind, severity, payload) VALUES (?, ?, ?, ?)",
            (iso(now_utc()), kind, severity, json.dumps(payload)),
        )
        return cur.lastrowid or 0

    def recent(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, ts_utc, kind, severity, payload "
            "FROM events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r[0],
                "ts": r[1],
                "kind": r[2],
                "severity": r[3],
                "payload": json.loads(r[4]),
            }
            for r in rows
        ]

    # --- scheduler persistence ----------------------------------------

    def schedule(self, eta_utc: datetime, kind: str, payload: dict) -> int:
        cur = self._conn.execute(
            "INSERT INTO scheduled (eta_utc, kind, payload) VALUES (?, ?, ?)",
            (iso(eta_utc), kind, json.dumps(payload)),
        )
        return cur.lastrowid or 0

    def pending(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, eta_utc, kind, payload "
            "FROM scheduled WHERE fired = 0 ORDER BY eta_utc"
        ).fetchall()
        return [
            {"id": r[0], "eta": r[1], "kind": r[2], "payload": json.loads(r[3])}
            for r in rows
        ]

    def mark_fired(self, scheduled_id: int) -> None:
        self._conn.execute(
            "UPDATE scheduled SET fired = 1 WHERE id = ?", (scheduled_id,)
        )

    # --- entities: sites / hosts / vms / tapes ------------------------

    def count_sites(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM sites").fetchone()[0])

    def create_site(self, name: str, site_type: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO sites (name, site_type, created_at) VALUES (?, ?, ?)",
            (name, site_type, iso(now_utc())),
        )
        return cur.lastrowid or 0

    def list_sites(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, name, site_type, created_at FROM sites ORDER BY id"
        ).fetchall()
        return [{"id": r[0], "name": r[1], "type": r[2], "created_at": r[3]} for r in rows]

    def create_host(
        self, site_id: int, name: str, host_class: str, specs: dict, status: str
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO hosts (site_id, name, host_class, specs, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (site_id, name, host_class, json.dumps(specs), status),
        )
        return cur.lastrowid or 0

    _HOST_COLS = "id, site_id, name, host_class, specs, status, transit_to_site_id"

    def list_hosts(self) -> list[dict]:
        rows = self._conn.execute(
            f"SELECT {self._HOST_COLS} FROM hosts ORDER BY id"
        ).fetchall()
        return [self._host_row(r) for r in rows]

    def get_host(self, host_id: int) -> dict | None:
        row = self._conn.execute(
            f"SELECT {self._HOST_COLS} FROM hosts WHERE id = ?", (host_id,)
        ).fetchone()
        return self._host_row(row) if row else None

    @staticmethod
    def _host_row(r: tuple) -> dict:
        return {
            "id": r[0],
            "site_id": r[1],
            "name": r[2],
            "class": r[3],
            "specs": json.loads(r[4]),
            "status": r[5],
            "transit_to_site_id": r[6],
        }

    def set_host_status(self, host_id: int, status: str) -> None:
        self._conn.execute("UPDATE hosts SET status = ? WHERE id = ?", (status, host_id))

    def set_host_site(self, host_id: int, site_id: int) -> None:
        self._conn.execute("UPDATE hosts SET site_id = ? WHERE id = ?", (site_id, host_id))

    def set_host_transit(self, host_id: int, to_site_id: int | None) -> None:
        self._conn.execute(
            "UPDATE hosts SET transit_to_site_id = ? WHERE id = ?",
            (to_site_id, host_id),
        )

    def create_vm(self, host_id: int, name: str, spec: dict, status: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO vms (host_id, name, spec, status) VALUES (?, ?, ?, ?)",
            (host_id, name, json.dumps(spec), status),
        )
        return cur.lastrowid or 0

    def count_vms_on_host(self, host_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM vms WHERE host_id = ?",
            (int(host_id),),
        ).fetchone()
        return int(row[0]) if row else 0

    def list_vms(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT v.id, v.host_id, v.name, v.spec, v.status, h.status "
            "FROM vms v JOIN hosts h ON v.host_id = h.id "
            "ORDER BY v.id"
        ).fetchall()
        return [
            {
                "id": r[0],
                "host_id": r[1],
                "name": r[2],
                "spec": json.loads(r[3]),
                "status": r[4],
                "host_status": r[5],
            }
            for r in rows
        ]

    def get_vm(self, vm_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT v.id, v.host_id, v.name, v.spec, v.status, h.status "
            "FROM vms v JOIN hosts h ON v.host_id = h.id "
            "WHERE v.id = ?",
            (vm_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "host_id": row[1],
            "name": row[2],
            "spec": json.loads(row[3]),
            "status": row[4],
            "host_status": row[5],
        }

    def set_vm_status(self, vm_id: int, status: str) -> None:
        self._conn.execute("UPDATE vms SET status = ? WHERE id = ?", (status, vm_id))

    def set_vms_on_host_status(self, host_id: int, status: str) -> None:
        self._conn.execute(
            "UPDATE vms SET status = ? WHERE host_id = ?", (status, host_id)
        )

    def create_tape_drive(self, site_id: int, name: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO tape_drives (site_id, name) VALUES (?, ?)", (site_id, name)
        )
        return cur.lastrowid or 0

    def list_tape_drives(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, site_id, name FROM tape_drives ORDER BY id"
        ).fetchall()
        return [{"id": r[0], "site_id": r[1], "name": r[2]} for r in rows]

    # --- items --------------------------------------------------------

    def create_item(
        self,
        designation: str,
        item_class: str,
        hazard_strength: int,
        profile: dict,
        state: str = "candidate",
    ) -> int:
        ts = iso(now_utc())
        # Pull size_gb from the profile at creation so items occupy real
        # storage on-disk from the moment they exist. A bare-dict profile
        # without a size field defaults to 0 (legacy safety).
        size_gb = float(profile.get("size_gb", 0) or 0)
        cur = self._conn.execute(
            "INSERT INTO items (designation, item_class, hazard_strength, profile, "
            "state, size_gb, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                designation, item_class, hazard_strength,
                json.dumps(profile), state, size_gb, ts, ts,
            ),
        )
        return cur.lastrowid or 0

    _ITEM_COLS = (
        "id, designation, item_class, hazard_strength, profile, state, "
        "current_vm_id, created_at, updated_at, current_site_id, transit_to_site_id, "
        "size_gb, encrypted_at_rest"
    )

    def list_items(self, state: str | None = None) -> list[dict]:
        if state is not None:
            rows = self._conn.execute(
                f"SELECT {self._ITEM_COLS} FROM items WHERE state = ? ORDER BY id",
                (state,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT {self._ITEM_COLS} FROM items ORDER BY id"
            ).fetchall()
        return [self._item_row(r) for r in rows]

    def get_item(self, item_id: int) -> dict | None:
        row = self._conn.execute(
            f"SELECT {self._ITEM_COLS} FROM items WHERE id = ?",
            (item_id,),
        ).fetchone()
        return self._item_row(row) if row else None

    @staticmethod
    def _item_row(r: tuple) -> dict:
        return {
            "id": r[0],
            "designation": r[1],
            "class": r[2],
            "hazard_strength": r[3],
            "profile": json.loads(r[4]),
            "state": r[5],
            "current_vm_id": r[6],
            "created_at": r[7],
            "updated_at": r[8],
            "current_site_id": r[9],
            "transit_to_site_id": r[10],
            "size_gb": float(r[11] or 0),
            "encrypted_at_rest": bool(r[12] or 0),
        }

    def set_item_state(
        self, item_id: int, state: str, current_vm_id: int | None = -1
    ) -> None:
        ts = iso(now_utc())
        if current_vm_id == -1:
            self._conn.execute(
                "UPDATE items SET state = ?, updated_at = ? WHERE id = ?",
                (state, ts, item_id),
            )
        else:
            self._conn.execute(
                "UPDATE items SET state = ?, current_vm_id = ?, updated_at = ? "
                "WHERE id = ?",
                (state, current_vm_id, ts, item_id),
            )

    def set_item_site(self, item_id: int, current_site_id: int | None) -> None:
        self._conn.execute(
            "UPDATE items SET current_site_id = ?, updated_at = ? WHERE id = ?",
            (current_site_id, iso(now_utc()), item_id),
        )

    def set_item_transit(
        self, item_id: int, to_site_id: int | None
    ) -> None:
        self._conn.execute(
            "UPDATE items SET transit_to_site_id = ?, updated_at = ? WHERE id = ?",
            (to_site_id, iso(now_utc()), item_id),
        )

    def set_item_size(self, item_id: int, size_gb: float) -> None:
        self._conn.execute(
            "UPDATE items SET size_gb = ?, updated_at = ? WHERE id = ?",
            (float(size_gb), iso(now_utc()), item_id),
        )

    def set_item_encryption(self, item_id: int, encrypted: bool) -> None:
        self._conn.execute(
            "UPDATE items SET encrypted_at_rest = ?, updated_at = ? WHERE id = ?",
            (1 if encrypted else 0, iso(now_utc()), item_id),
        )

    # --- settings (key/value) -----------------------------------------

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )

    def get_time_multiplier(self) -> float:
        """Runtime time-compression factor. 1.0 = real-time; 10.0 = 10×
        faster than wall clock; 0.0001 = effectively paused. Scheduler
        divides its sleep by this value."""
        raw = self.get_setting("time_multiplier", "1.0")
        try:
            return float(raw or 1.0)
        except (TypeError, ValueError):
            return 1.0

    def set_time_multiplier(self, value: float) -> float:
        # Clamp to avoid divide-by-zero and absurd values
        v = max(0.0001, min(10_000.0, float(value)))
        self.set_setting("time_multiplier", f"{v}")
        return v

    # --- funding ------------------------------------------------------

    def get_funding(self) -> int:
        row = self._conn.execute("SELECT balance FROM funding WHERE id = 1").fetchone()
        return int(row[0]) if row else 0

    def set_funding(self, balance: int) -> None:
        self._conn.execute(
            "INSERT INTO funding (id, balance) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET balance = excluded.balance",
            (balance,),
        )

    def adjust_funding(self, delta: int) -> int:
        current = self.get_funding()
        new_balance = current + delta
        self.set_funding(new_balance)
        return new_balance

    # --- staff --------------------------------------------------------

    def count_staff(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM staff").fetchone()[0])

    def create_staff(
        self,
        name: str,
        role: str,
        is_player: bool,
        skills: dict,
        clearance: int,
        salary: int,
        assigned_site_id: int | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO staff (name, role, is_player, skills, clearance, "
            "status, assigned_site_id, salary, hired_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                role,
                1 if is_player else 0,
                json.dumps(skills),
                clearance,
                "active",
                assigned_site_id,
                salary,
                iso(now_utc()),
            ),
        )
        return cur.lastrowid or 0

    _STAFF_COLS = (
        "id, name, role, is_player, skills, clearance, status, "
        "assigned_site_id, salary, hired_at, transit_to_site_id, autonomy"
    )

    def list_staff(self) -> list[dict]:
        rows = self._conn.execute(
            f"SELECT {self._STAFF_COLS} FROM staff ORDER BY id"
        ).fetchall()
        return [self._staff_row(r) for r in rows]

    def get_staff(self, staff_id: int) -> dict | None:
        row = self._conn.execute(
            f"SELECT {self._STAFF_COLS} FROM staff WHERE id = ?", (staff_id,)
        ).fetchone()
        return self._staff_row(row) if row else None

    def get_player(self) -> dict | None:
        row = self._conn.execute(
            f"SELECT {self._STAFF_COLS} FROM staff WHERE is_player = 1 "
            "ORDER BY id LIMIT 1"
        ).fetchone()
        return self._staff_row(row) if row else None

    @staticmethod
    def _staff_row(r: tuple) -> dict:
        return {
            "id": r[0],
            "name": r[1],
            "role": r[2],
            "is_player": bool(r[3]),
            "skills": json.loads(r[4]),
            "clearance": r[5],
            "status": r[6],
            "assigned_site_id": r[7],
            "salary": r[8],
            "hired_at": r[9],
            "transit_to_site_id": r[10],
            "autonomy": r[11] or "off",
        }

    def set_staff_autonomy(self, staff_id: int, mode: str) -> None:
        if mode not in ("off", "on"):
            raise ValueError(f"unknown autonomy mode: {mode}")
        self._conn.execute(
            "UPDATE staff SET autonomy = ? WHERE id = ?", (mode, staff_id)
        )

    def set_staff_assignment(self, staff_id: int, site_id: int) -> None:
        self._conn.execute(
            "UPDATE staff SET assigned_site_id = ? WHERE id = ?",
            (site_id, staff_id),
        )

    def set_staff_transit(self, staff_id: int, to_site_id: int | None) -> None:
        self._conn.execute(
            "UPDATE staff SET transit_to_site_id = ? WHERE id = ?",
            (to_site_id, staff_id),
        )

    def update_staff_skills(self, staff_id: int, skills: dict) -> None:
        self._conn.execute(
            "UPDATE staff SET skills = ? WHERE id = ?",
            (json.dumps(skills), staff_id),
        )

    def set_staff_status(self, staff_id: int, status: str) -> None:
        self._conn.execute(
            "UPDATE staff SET status = ? WHERE id = ?", (status, staff_id)
        )

    def add_skill_direct(self, staff_id: int, skill: str, gain: int) -> tuple[int, int]:
        """Directly add to a skill (no diminishing returns). For training."""
        s = self.get_staff(staff_id)
        if not s:
            return (0, 0)
        current = int(s["skills"].get(skill, 0))
        after = min(100, current + int(gain))
        skills = dict(s["skills"])
        skills[skill] = after
        self.update_staff_skills(staff_id, skills)
        return (current, after)

    def grant_xp(self, staff_id: int, skill: str, delta: int) -> tuple[int, int]:
        """Return (before, after) skill level. Diminishing returns built in."""
        s = self.get_staff(staff_id)
        if not s:
            return (0, 0)
        current = int(s["skills"].get(skill, 0))
        # Diminishing returns: scale delta by (1 - current/100)
        gain = max(0, round(delta * (1 - current / 100)))
        after = min(100, current + gain)
        skills = dict(s["skills"])
        skills[skill] = after
        self.update_staff_skills(staff_id, skills)
        return (current, after)

    # --- mistakes -----------------------------------------------------

    def record_mistake(
        self,
        kind: str,
        action: str,
        operator_id: int | None,
        item_id: int | None,
        host_id: int | None,
        vm_id: int | None,
        overridden: bool,
        details: dict,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO mistakes (ts_utc, kind, action, operator_id, item_id, "
            "host_id, vm_id, overridden, details) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                iso(now_utc()),
                kind,
                action,
                operator_id,
                item_id,
                host_id,
                vm_id,
                1 if overridden else 0,
                json.dumps(details),
            ),
        )
        return cur.lastrowid or 0

    def recent_mistakes(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, ts_utc, kind, action, operator_id, item_id, host_id, "
            "vm_id, overridden, details FROM mistakes ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r[0],
                "ts": r[1],
                "kind": r[2],
                "action": r[3],
                "operator_id": r[4],
                "item_id": r[5],
                "host_id": r[6],
                "vm_id": r[7],
                "overridden": bool(r[8]),
                "details": json.loads(r[9]),
            }
            for r in rows
        ]

    def mistakes_for_item(self, item_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, ts_utc, kind, action, operator_id, item_id, host_id, "
            "vm_id, overridden, details FROM mistakes WHERE item_id = ? "
            "ORDER BY id",
            (item_id,),
        ).fetchall()
        return [
            {
                "id": r[0],
                "ts": r[1],
                "kind": r[2],
                "action": r[3],
                "operator_id": r[4],
                "item_id": r[5],
                "host_id": r[6],
                "vm_id": r[7],
                "overridden": bool(r[8]),
                "details": json.loads(r[9]),
            }
            for r in rows
        ]

    # --- incidents ----------------------------------------------------

    def create_incident(
        self,
        severity: str,
        item_id: int | None,
        host_id: int | None,
        vm_id: int | None,
        operator_id: int | None,
        vector: str,
        root_cause: str,
        contributing: list[str],
        exposure: dict,
        recommend: list[str],
        mistake_ids: list[int],
        report: str,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO incidents (ts_utc, severity, item_id, host_id, vm_id, "
            "operator_id, vector, root_cause, contributing, exposure, recommend, "
            "mistake_ids, report) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                iso(now_utc()),
                severity,
                item_id,
                host_id,
                vm_id,
                operator_id,
                vector,
                root_cause,
                json.dumps(contributing),
                json.dumps(exposure),
                json.dumps(recommend),
                json.dumps(mistake_ids),
                report,
            ),
        )
        return cur.lastrowid or 0

    def list_incidents(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, ts_utc, severity, item_id, host_id, vm_id, operator_id, "
            "vector, root_cause, contributing, exposure, recommend, mistake_ids, "
            "report FROM incidents ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._incident_row(r) for r in rows]

    def get_incident(self, incident_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT id, ts_utc, severity, item_id, host_id, vm_id, operator_id, "
            "vector, root_cause, contributing, exposure, recommend, mistake_ids, "
            "report FROM incidents WHERE id = ?",
            (incident_id,),
        ).fetchone()
        return self._incident_row(row) if row else None

    @staticmethod
    def _incident_row(r: tuple) -> dict:
        return {
            "id": r[0],
            "ts": r[1],
            "severity": r[2],
            "item_id": r[3],
            "host_id": r[4],
            "vm_id": r[5],
            "operator_id": r[6],
            "vector": r[7],
            "root_cause": r[8],
            "contributing": json.loads(r[9]),
            "exposure": json.loads(r[10]),
            "recommend": json.loads(r[11]),
            "mistake_ids": json.loads(r[12]),
            "report": r[13],
        }

    # --- site capacity ------------------------------------------------

    def set_site_capacity(self, site_id: int, power_kw: int, cooling_kw: int) -> None:
        self._conn.execute(
            "INSERT INTO site_capacity (site_id, power_kw, cooling_kw) "
            "VALUES (?, ?, ?) ON CONFLICT(site_id) DO UPDATE SET "
            "power_kw = excluded.power_kw, cooling_kw = excluded.cooling_kw",
            (site_id, power_kw, cooling_kw),
        )

    def get_site_capacity(self, site_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT site_id, power_kw, cooling_kw FROM site_capacity WHERE site_id = ?",
            (site_id,),
        ).fetchone()
        if not row:
            return None
        return {"site_id": row[0], "power_kw": row[1], "cooling_kw": row[2]}

    # --- vm spec update (for upgrade modules) -------------------------

    def update_vm_spec(self, vm_id: int, spec: dict) -> None:
        self._conn.execute(
            "UPDATE vms SET spec = ? WHERE id = ?",
            (json.dumps(spec), vm_id),
        )

    # --- purchases ----------------------------------------------------

    def create_purchase(
        self,
        sku: str,
        price_usd: int,
        target_site_id: int | None,
        target_vm_id: int | None,
        eta_utc,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO purchases (sku, price_usd, status, target_site_id, "
            "target_vm_id, ordered_at, eta_utc) VALUES (?, ?, 'ordered', ?, ?, ?, ?)",
            (sku, price_usd, target_site_id, target_vm_id, iso(now_utc()), iso(eta_utc)),
        )
        return cur.lastrowid or 0

    def get_purchase(self, purchase_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT id, sku, price_usd, status, target_site_id, target_vm_id, "
            "ordered_at, eta_utc, installed_at FROM purchases WHERE id = ?",
            (purchase_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "sku": row[1],
            "price_usd": row[2],
            "status": row[3],
            "target_site_id": row[4],
            "target_vm_id": row[5],
            "ordered_at": row[6],
            "eta_utc": row[7],
            "installed_at": row[8],
        }

    def list_purchases(self, status: str | None = None) -> list[dict]:
        if status:
            rows = self._conn.execute(
                "SELECT id, sku, price_usd, status, target_site_id, target_vm_id, "
                "ordered_at, eta_utc, installed_at FROM purchases WHERE status = ? "
                "ORDER BY id DESC",
                (status,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, sku, price_usd, status, target_site_id, target_vm_id, "
                "ordered_at, eta_utc, installed_at FROM purchases ORDER BY id DESC"
            ).fetchall()
        return [
            {
                "id": r[0],
                "sku": r[1],
                "price_usd": r[2],
                "status": r[3],
                "target_site_id": r[4],
                "target_vm_id": r[5],
                "ordered_at": r[6],
                "eta_utc": r[7],
                "installed_at": r[8],
            }
            for r in rows
        ]

    def mark_purchase_installed(self, purchase_id: int) -> None:
        self._conn.execute(
            "UPDATE purchases SET status = 'installed', installed_at = ? WHERE id = ?",
            (iso(now_utc()), purchase_id),
        )

    # --- enrollments (training) ---------------------------------------

    def create_enrollment(
        self, staff_id: int, course_id: str, eta_utc
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO enrollments (staff_id, course_id, status, enrolled_at, "
            "eta_utc) VALUES (?, ?, 'enrolled', ?, ?)",
            (staff_id, course_id, iso(now_utc()), iso(eta_utc)),
        )
        return cur.lastrowid or 0

    def get_enrollment(self, enrollment_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT id, staff_id, course_id, status, enrolled_at, eta_utc, "
            "completed_at FROM enrollments WHERE id = ?",
            (enrollment_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "staff_id": row[1],
            "course_id": row[2],
            "status": row[3],
            "enrolled_at": row[4],
            "eta_utc": row[5],
            "completed_at": row[6],
        }

    def list_enrollments(
        self, staff_id: int | None = None, status: str | None = None
    ) -> list[dict]:
        q = (
            "SELECT id, staff_id, course_id, status, enrolled_at, eta_utc, "
            "completed_at FROM enrollments"
        )
        conds: list[str] = []
        params: list = []
        if staff_id is not None:
            conds.append("staff_id = ?")
            params.append(staff_id)
        if status is not None:
            conds.append("status = ?")
            params.append(status)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY id DESC"
        rows = self._conn.execute(q, params).fetchall()
        return [
            {
                "id": r[0],
                "staff_id": r[1],
                "course_id": r[2],
                "status": r[3],
                "enrolled_at": r[4],
                "eta_utc": r[5],
                "completed_at": r[6],
            }
            for r in rows
        ]

    def mark_enrollment_graduated(self, enrollment_id: int) -> None:
        self._conn.execute(
            "UPDATE enrollments SET status = 'graduated', completed_at = ? "
            "WHERE id = ?",
            (iso(now_utc()), enrollment_id),
        )

    def has_completed_course(self, staff_id: int, course_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM enrollments WHERE staff_id = ? AND course_id = ? "
            "AND status = 'graduated' LIMIT 1",
            (staff_id, course_id),
        ).fetchone()
        return row is not None

    # --- site network -------------------------------------------------

    def set_site_network(self, site_id: int, tier: str) -> None:
        self._conn.execute(
            "INSERT INTO site_network (site_id, tier) VALUES (?, ?) "
            "ON CONFLICT(site_id) DO UPDATE SET tier = excluded.tier",
            (site_id, tier),
        )

    def get_site_network(self, site_id: int) -> str | None:
        row = self._conn.execute(
            "SELECT tier FROM site_network WHERE site_id = ?", (site_id,)
        ).fetchone()
        return row[0] if row else None

    def list_site_networks(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT site_id, tier FROM site_network ORDER BY site_id"
        ).fetchall()
        return [{"site_id": r[0], "tier": r[1]} for r in rows]

    # --- site encryption ----------------------------------------------

    def set_site_encryption(self, site_id: int, level: str) -> None:
        self._conn.execute(
            "INSERT INTO site_encryption (site_id, level, installed_at) "
            "VALUES (?, ?, ?) ON CONFLICT(site_id) DO UPDATE SET "
            "level = excluded.level, installed_at = excluded.installed_at",
            (site_id, level, iso(now_utc())),
        )

    def get_site_encryption(self, site_id: int) -> str:
        row = self._conn.execute(
            "SELECT level FROM site_encryption WHERE site_id = ?", (site_id,)
        ).fetchone()
        return row[0] if row else "none"

    # --- playbooks ----------------------------------------------------

    def get_playbook(self, site_id: int) -> dict:
        row = self._conn.execute(
            "SELECT rules FROM playbooks WHERE site_id = ?", (site_id,)
        ).fetchone()
        if not row:
            return {}
        try:
            return json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            return {}

    def set_playbook(self, site_id: int, rules: dict) -> None:
        self._conn.execute(
            "INSERT INTO playbooks (site_id, rules) VALUES (?, ?) "
            "ON CONFLICT(site_id) DO UPDATE SET rules = excluded.rules",
            (site_id, json.dumps(rules)),
        )

    # --- airfield + aircraft ------------------------------------------

    def set_site_airfield(self, site_id: int, tier: str) -> None:
        self._conn.execute(
            "INSERT INTO site_airfield (site_id, tier) VALUES (?, ?) "
            "ON CONFLICT(site_id) DO UPDATE SET tier = excluded.tier",
            (site_id, tier),
        )

    def get_site_airfield(self, site_id: int) -> str:
        row = self._conn.execute(
            "SELECT tier FROM site_airfield WHERE site_id = ?", (site_id,)
        ).fetchone()
        return row[0] if row else "none"

    def create_aircraft(
        self,
        site_id: int,
        tail_number: str,
        sku: str,
        aircraft_class: str,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO aircraft (site_id, tail_number, sku, aircraft_class, "
            "status, purchased_at) VALUES (?, ?, ?, ?, 'parked', ?)",
            (site_id, tail_number, sku, aircraft_class, iso(now_utc())),
        )
        return cur.lastrowid or 0

    def list_aircraft(self, site_id: int | None = None) -> list[dict]:
        if site_id is not None:
            rows = self._conn.execute(
                "SELECT id, site_id, tail_number, sku, aircraft_class, status, "
                "purchased_at FROM aircraft WHERE site_id = ? ORDER BY id",
                (site_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, site_id, tail_number, sku, aircraft_class, status, "
                "purchased_at FROM aircraft ORDER BY id"
            ).fetchall()
        return [
            {
                "id": r[0],
                "site_id": r[1],
                "tail_number": r[2],
                "sku": r[3],
                "class": r[4],
                "status": r[5],
                "purchased_at": r[6],
            }
            for r in rows
        ]

    def count_aircraft(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM aircraft").fetchone()
        return int(row[0]) if row else 0

    # --- ports + ships ------------------------------------------------

    def set_site_port(self, site_id: int, tier: str) -> None:
        self._conn.execute(
            "INSERT INTO site_port (site_id, tier) VALUES (?, ?) "
            "ON CONFLICT(site_id) DO UPDATE SET tier = excluded.tier",
            (site_id, tier),
        )

    def get_site_port(self, site_id: int) -> str:
        row = self._conn.execute(
            "SELECT tier FROM site_port WHERE site_id = ?", (site_id,)
        ).fetchone()
        return row[0] if row else "none"

    def create_ship(
        self,
        site_id: int,
        hull_number: str,
        sku: str,
        ship_class: str,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO ships (site_id, hull_number, sku, ship_class, "
            "status, purchased_at) VALUES (?, ?, ?, ?, 'berthed', ?)",
            (site_id, hull_number, sku, ship_class, iso(now_utc())),
        )
        return cur.lastrowid or 0

    def list_ships(self, site_id: int | None = None) -> list[dict]:
        if site_id is not None:
            rows = self._conn.execute(
                "SELECT id, site_id, hull_number, sku, ship_class, status, "
                "purchased_at FROM ships WHERE site_id = ? ORDER BY id",
                (site_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, site_id, hull_number, sku, ship_class, status, "
                "purchased_at FROM ships ORDER BY id"
            ).fetchall()
        return [
            {
                "id": r[0],
                "site_id": r[1],
                "hull_number": r[2],
                "sku": r[3],
                "class": r[4],
                "status": r[5],
                "purchased_at": r[6],
            }
            for r in rows
        ]

    def count_ships(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM ships").fetchone()
        return int(row[0]) if row else 0

    # --- satellites + ground stations ---------------------------------

    def create_satellite(
        self,
        callsign: str,
        sku: str,
        satellite_class: str,
        orbit: str,
        payload: str,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO satellites (callsign, sku, satellite_class, orbit, "
            "payload, status, launched_at) VALUES (?, ?, ?, ?, ?, 'on_orbit', ?)",
            (callsign, sku, satellite_class, orbit, payload, iso(now_utc())),
        )
        return cur.lastrowid or 0

    def list_satellites(self, payload: str | None = None) -> list[dict]:
        if payload is not None:
            rows = self._conn.execute(
                "SELECT id, callsign, sku, satellite_class, orbit, payload, "
                "status, launched_at FROM satellites WHERE payload = ? "
                "ORDER BY id",
                (payload,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, callsign, sku, satellite_class, orbit, payload, "
                "status, launched_at FROM satellites ORDER BY id"
            ).fetchall()
        return [
            {
                "id": r[0],
                "callsign": r[1],
                "sku": r[2],
                "class": r[3],
                "orbit": r[4],
                "payload": r[5],
                "status": r[6],
                "launched_at": r[7],
            }
            for r in rows
        ]

    def count_satellites(self, payload: str | None = None) -> int:
        if payload is not None:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM satellites WHERE payload = ? AND status = 'on_orbit'",
                (payload,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM satellites WHERE status = 'on_orbit'"
            ).fetchone()
        return int(row[0]) if row else 0

    def set_site_ground_station(self, site_id: int, tier: str) -> None:
        self._conn.execute(
            "INSERT INTO site_ground_station (site_id, tier) VALUES (?, ?) "
            "ON CONFLICT(site_id) DO UPDATE SET tier = excluded.tier",
            (site_id, tier),
        )

    def get_site_ground_station(self, site_id: int) -> str:
        row = self._conn.execute(
            "SELECT tier FROM site_ground_station WHERE site_id = ?", (site_id,)
        ).fetchone()
        return row[0] if row else "none"

    # --- submarines ---------------------------------------------------

    def create_submarine(
        self,
        site_id: int,
        hull_number: str,
        sku: str,
        sub_class: str,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO submarines (site_id, hull_number, sku, sub_class, "
            "status, purchased_at) VALUES (?, ?, ?, ?, 'berthed', ?)",
            (site_id, hull_number, sku, sub_class, iso(now_utc())),
        )
        return cur.lastrowid or 0

    def list_submarines(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, site_id, hull_number, sku, sub_class, status, "
            "purchased_at FROM submarines ORDER BY id"
        ).fetchall()
        return [
            {
                "id": r[0],
                "site_id": r[1],
                "hull_number": r[2],
                "sku": r[3],
                "class": r[4],
                "status": r[5],
                "purchased_at": r[6],
            }
            for r in rows
        ]

    def count_submarines(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM submarines").fetchone()
        return int(row[0]) if row else 0

    # --- vessel status/site updates (ships + subs share the API) -----

    def _vessel_table(self, vessel_type: str) -> str:
        if vessel_type == "ship":
            return "ships"
        if vessel_type == "submarine":
            return "submarines"
        raise ValueError(f"bad vessel_type '{vessel_type}'")

    def set_vessel_status(self, vessel_type: str, vessel_id: int, status: str) -> None:
        table = self._vessel_table(vessel_type)
        self._conn.execute(
            f"UPDATE {table} SET status = ? WHERE id = ?",
            (status, int(vessel_id)),
        )

    def set_vessel_site(self, vessel_type: str, vessel_id: int, site_id: int) -> None:
        table = self._vessel_table(vessel_type)
        self._conn.execute(
            f"UPDATE {table} SET site_id = ? WHERE id = ?",
            (int(site_id), int(vessel_id)),
        )

    # --- vessel equipment ---------------------------------------------

    def install_vessel_equipment(
        self, vessel_type: str, vessel_id: int, sku: str
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO vessel_equipment (vessel_type, vessel_id, sku, "
            "installed_at) VALUES (?, ?, ?, ?)",
            (vessel_type, int(vessel_id), sku, iso(now_utc())),
        )
        return cur.lastrowid or 0

    def list_vessel_equipment(
        self,
        vessel_type: str | None = None,
        vessel_id: int | None = None,
    ) -> list[dict]:
        clauses, binds = [], []
        if vessel_type is not None:
            clauses.append("vessel_type = ?")
            binds.append(vessel_type)
        if vessel_id is not None:
            clauses.append("vessel_id = ?")
            binds.append(int(vessel_id))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            f"SELECT id, vessel_type, vessel_id, sku, installed_at "
            f"FROM vessel_equipment{where} ORDER BY id",
            tuple(binds),
        ).fetchall()
        return [
            {
                "id": r[0],
                "vessel_type": r[1],
                "vessel_id": r[2],
                "sku": r[3],
                "installed_at": r[4],
            }
            for r in rows
        ]

    def get_vessel_equipment(self, equipment_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT id, vessel_type, vessel_id, sku, installed_at "
            "FROM vessel_equipment WHERE id = ?",
            (int(equipment_id),),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0], "vessel_type": row[1], "vessel_id": row[2],
            "sku": row[3], "installed_at": row[4],
        }

    def remove_vessel_equipment(self, equipment_id: int) -> None:
        self._conn.execute(
            "DELETE FROM vessel_equipment WHERE id = ?", (int(equipment_id),)
        )

    # --- site security equipment -------------------------------------

    def install_site_security(self, site_id: int, sku: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO site_security_equipment (site_id, sku, installed_at) "
            "VALUES (?, ?, ?)",
            (int(site_id), sku, iso(now_utc())),
        )
        return cur.lastrowid or 0

    def list_site_security(self, site_id: int | None = None) -> list[dict]:
        if site_id is not None:
            rows = self._conn.execute(
                "SELECT id, site_id, sku, installed_at "
                "FROM site_security_equipment WHERE site_id = ? ORDER BY id",
                (int(site_id),),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, site_id, sku, installed_at "
                "FROM site_security_equipment ORDER BY id"
            ).fetchall()
        return [
            {
                "id": r[0], "site_id": r[1], "sku": r[2],
                "installed_at": r[3],
            }
            for r in rows
        ]

    def get_site_security_row(self, equipment_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT id, site_id, sku, installed_at "
            "FROM site_security_equipment WHERE id = ?",
            (int(equipment_id),),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0], "site_id": row[1], "sku": row[2],
            "installed_at": row[3],
        }

    def remove_site_security(self, equipment_id: int) -> None:
        self._conn.execute(
            "DELETE FROM site_security_equipment WHERE id = ?",
            (int(equipment_id),),
        )

    # --- vessel orders ------------------------------------------------

    def create_vessel_order(
        self,
        vessel_type: str,
        vessel_id: int,
        kind: str,
        params_json: str,
        eta_iso: str,
        payout_usd: int,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO vessel_orders (vessel_type, vessel_id, kind, "
            "params_json, state, started_at, eta_utc, payout_usd) "
            "VALUES (?, ?, ?, ?, 'active', ?, ?, ?)",
            (
                vessel_type, int(vessel_id), kind, params_json,
                iso(now_utc()), eta_iso, int(payout_usd),
            ),
        )
        return cur.lastrowid or 0

    def set_vessel_order_scheduled_id(self, order_id: int, sid: int) -> None:
        self._conn.execute(
            "UPDATE vessel_orders SET scheduled_id = ? WHERE id = ?",
            (int(sid), int(order_id)),
        )

    def get_vessel_order(self, order_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT id, vessel_type, vessel_id, kind, params_json, state, "
            "started_at, eta_utc, payout_usd, scheduled_id, effect_json "
            "FROM vessel_orders WHERE id = ?",
            (int(order_id),),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0], "vessel_type": row[1], "vessel_id": row[2],
            "kind": row[3], "params_json": row[4], "state": row[5],
            "started_at": row[6], "eta_utc": row[7],
            "payout_usd": row[8], "scheduled_id": row[9],
            "effect_json": row[10],
        }

    def get_active_vessel_order(
        self, vessel_type: str, vessel_id: int
    ) -> dict | None:
        row = self._conn.execute(
            "SELECT id, vessel_type, vessel_id, kind, params_json, state, "
            "started_at, eta_utc, payout_usd, scheduled_id, effect_json "
            "FROM vessel_orders "
            "WHERE vessel_type = ? AND vessel_id = ? AND state = 'active' "
            "LIMIT 1",
            (vessel_type, int(vessel_id)),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0], "vessel_type": row[1], "vessel_id": row[2],
            "kind": row[3], "params_json": row[4], "state": row[5],
            "started_at": row[6], "eta_utc": row[7],
            "payout_usd": row[8], "scheduled_id": row[9],
            "effect_json": row[10],
        }

    def list_vessel_orders(
        self,
        vessel_type: str | None = None,
        vessel_id: int | None = None,
        state: str | None = None,
    ) -> list[dict]:
        clauses, binds = [], []
        if vessel_type is not None:
            clauses.append("vessel_type = ?")
            binds.append(vessel_type)
        if vessel_id is not None:
            clauses.append("vessel_id = ?")
            binds.append(int(vessel_id))
        if state is not None:
            clauses.append("state = ?")
            binds.append(state)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            f"SELECT id, vessel_type, vessel_id, kind, params_json, state, "
            f"started_at, eta_utc, payout_usd, scheduled_id, effect_json "
            f"FROM vessel_orders{where} ORDER BY id DESC",
            tuple(binds),
        ).fetchall()
        return [
            {
                "id": r[0], "vessel_type": r[1], "vessel_id": r[2],
                "kind": r[3], "params_json": r[4], "state": r[5],
                "started_at": r[6], "eta_utc": r[7],
                "payout_usd": r[8], "scheduled_id": r[9],
                "effect_json": r[10],
            }
            for r in rows
        ]

    def set_vessel_order_state(
        self, order_id: int, state: str, effect_json: str | None = None
    ) -> None:
        if effect_json is None:
            self._conn.execute(
                "UPDATE vessel_orders SET state = ? WHERE id = ?",
                (state, int(order_id)),
            )
        else:
            self._conn.execute(
                "UPDATE vessel_orders SET state = ?, effect_json = ? WHERE id = ?",
                (state, effect_json, int(order_id)),
            )

    # --- power plants -------------------------------------------------

    def create_power_plant(
        self,
        site_id: int,
        sku: str,
        plant_type: str,
        kw_rating: int,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO power_plants (site_id, sku, plant_type, kw_rating, "
            "status, installed_at) VALUES (?, ?, ?, ?, 'online', ?)",
            (site_id, sku, plant_type, kw_rating, iso(now_utc())),
        )
        return cur.lastrowid or 0

    def list_power_plants(self, site_id: int | None = None) -> list[dict]:
        if site_id is not None:
            rows = self._conn.execute(
                "SELECT id, site_id, sku, plant_type, kw_rating, status, "
                "installed_at FROM power_plants WHERE site_id = ? ORDER BY id",
                (site_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, site_id, sku, plant_type, kw_rating, status, "
                "installed_at FROM power_plants ORDER BY id"
            ).fetchall()
        return [
            {
                "id": r[0],
                "site_id": r[1],
                "sku": r[2],
                "plant_type": r[3],
                "kw_rating": r[4],
                "status": r[5],
                "installed_at": r[6],
            }
            for r in rows
        ]

    def sum_site_power_plants_kw(self, site_id: int) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(kw_rating), 0) FROM power_plants "
            "WHERE site_id = ? AND status = 'online'",
            (site_id,),
        ).fetchone()
        return int(row[0]) if row else 0

    # --- site resilience (battery + fuel reserves) --------------------

    def get_site_resilience(self, site_id: int) -> dict:
        row = self._conn.execute(
            "SELECT battery_kwh, fuel_hours FROM site_resilience WHERE site_id = ?",
            (site_id,),
        ).fetchone()
        if not row:
            return {"battery_kwh": 0.0, "fuel_hours": 0.0}
        return {"battery_kwh": float(row[0]), "fuel_hours": float(row[1])}

    def add_site_battery(self, site_id: int, kwh: float) -> None:
        cur = self.get_site_resilience(site_id)
        new_kwh = cur["battery_kwh"] + float(kwh)
        self._conn.execute(
            "INSERT INTO site_resilience (site_id, battery_kwh, fuel_hours) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(site_id) DO UPDATE SET battery_kwh = excluded.battery_kwh",
            (site_id, new_kwh, cur["fuel_hours"]),
        )

    def add_site_fuel(self, site_id: int, hours: float) -> None:
        cur = self.get_site_resilience(site_id)
        new_h = cur["fuel_hours"] + float(hours)
        self._conn.execute(
            "INSERT INTO site_resilience (site_id, battery_kwh, fuel_hours) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(site_id) DO UPDATE SET fuel_hours = excluded.fuel_hours",
            (site_id, cur["battery_kwh"], new_h),
        )

    # --- outages ------------------------------------------------------

    def create_outage(
        self,
        site_id: int,
        kind: str,
        duration_h: float,
        ride_through: bool,
        eta_end_utc,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO outages (site_id, kind, duration_h, ride_through, "
            "started_at, eta_end_utc, status) VALUES (?, ?, ?, ?, ?, ?, 'active')",
            (
                site_id, kind, duration_h, 1 if ride_through else 0,
                iso(now_utc()), iso(eta_end_utc),
            ),
        )
        return cur.lastrowid or 0

    def active_outages(self, site_id: int | None = None) -> list[dict]:
        if site_id is not None:
            rows = self._conn.execute(
                "SELECT id, site_id, kind, duration_h, ride_through, started_at, "
                "eta_end_utc, status FROM outages WHERE status = 'active' "
                "AND site_id = ? ORDER BY id",
                (site_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, site_id, kind, duration_h, ride_through, started_at, "
                "eta_end_utc, status FROM outages WHERE status = 'active' ORDER BY id"
            ).fetchall()
        return [
            {
                "id": r[0],
                "site_id": r[1],
                "kind": r[2],
                "duration_h": r[3],
                "ride_through": bool(r[4]),
                "started_at": r[5],
                "eta_end_utc": r[6],
                "status": r[7],
            }
            for r in rows
        ]

    def resolve_outage(self, outage_id: int) -> None:
        self._conn.execute(
            "UPDATE outages SET status = 'resolved' WHERE id = ?", (outage_id,)
        )

    def list_playbooks(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT site_id, rules FROM playbooks ORDER BY site_id"
        ).fetchall()
        out: list[dict] = []
        for r in rows:
            try:
                parsed = json.loads(r[1])
            except Exception:
                parsed = {}
            out.append({"site_id": r[0], "rules": parsed})
        return out

    # --- contracts ----------------------------------------------------

    def create_contract(
        self,
        contract_type: str,
        target_site_id: int | None,
        target_vm_id: int | None,
        cost_per_period: int,
        period_seconds: float,
        details: dict,
        next_billing_utc,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO contracts (contract_type, target_site_id, target_vm_id, "
            "cost_per_period, period_seconds, status, details, started_at, "
            "next_billing_utc) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)",
            (
                contract_type,
                target_site_id,
                target_vm_id,
                cost_per_period,
                period_seconds,
                json.dumps(details),
                iso(now_utc()),
                iso(next_billing_utc),
            ),
        )
        return cur.lastrowid or 0

    def get_contract(self, contract_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT id, contract_type, target_site_id, target_vm_id, "
            "cost_per_period, period_seconds, status, details, started_at, "
            "next_billing_utc, last_billed_utc FROM contracts WHERE id = ?",
            (contract_id,),
        ).fetchone()
        if not row:
            return None
        return self._contract_row(row)

    def list_contracts(
        self,
        status: str | None = None,
        contract_type: str | None = None,
        target_vm_id: int | None = None,
    ) -> list[dict]:
        q = (
            "SELECT id, contract_type, target_site_id, target_vm_id, "
            "cost_per_period, period_seconds, status, details, started_at, "
            "next_billing_utc, last_billed_utc FROM contracts"
        )
        conds: list[str] = []
        params: list = []
        if status is not None:
            conds.append("status = ?")
            params.append(status)
        if contract_type is not None:
            conds.append("contract_type = ?")
            params.append(contract_type)
        if target_vm_id is not None:
            conds.append("target_vm_id = ?")
            params.append(target_vm_id)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY id DESC"
        rows = self._conn.execute(q, params).fetchall()
        return [self._contract_row(r) for r in rows]

    @staticmethod
    def _contract_row(r: tuple) -> dict:
        return {
            "id": r[0],
            "contract_type": r[1],
            "target_site_id": r[2],
            "target_vm_id": r[3],
            "cost_per_period": r[4],
            "period_seconds": r[5],
            "status": r[6],
            "details": json.loads(r[7]),
            "started_at": r[8],
            "next_billing_utc": r[9],
            "last_billed_utc": r[10],
        }

    def set_contract_status(self, contract_id: int, status: str) -> None:
        self._conn.execute(
            "UPDATE contracts SET status = ? WHERE id = ?", (status, contract_id)
        )

    def set_contract_next_billing(
        self, contract_id: int, next_billing_utc
    ) -> None:
        self._conn.execute(
            "UPDATE contracts SET next_billing_utc = ?, last_billed_utc = ? "
            "WHERE id = ?",
            (iso(next_billing_utc), iso(now_utc()), contract_id),
        )

    # --- storage arrays + tape libraries ------------------------------

    def create_storage_array(
        self, site_id: int, sku: str, capacity_gb: float, array_type: str
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO storage_arrays (site_id, sku, capacity_gb, array_type, "
            "status, installed_at) VALUES (?, ?, ?, ?, 'online', ?)",
            (site_id, sku, capacity_gb, array_type, iso(now_utc())),
        )
        return cur.lastrowid or 0

    def list_storage_arrays(self, site_id: int | None = None) -> list[dict]:
        if site_id is not None:
            rows = self._conn.execute(
                "SELECT id, site_id, sku, capacity_gb, array_type, status, "
                "installed_at FROM storage_arrays WHERE site_id = ? ORDER BY id",
                (site_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, site_id, sku, capacity_gb, array_type, status, "
                "installed_at FROM storage_arrays ORDER BY id"
            ).fetchall()
        return [
            {
                "id": r[0], "site_id": r[1], "sku": r[2],
                "capacity_gb": float(r[3]), "array_type": r[4],
                "status": r[5], "installed_at": r[6],
            } for r in rows
        ]

    def sum_site_storage_arrays_gb(self, site_id: int) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(capacity_gb), 0) FROM storage_arrays "
            "WHERE site_id = ? AND status = 'online'",
            (site_id,),
        ).fetchone()
        return float(row[0]) if row else 0.0

    def create_tape_library(
        self, site_id: int, sku: str, capacity_gb: float
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO tape_libraries (site_id, sku, capacity_gb, status, "
            "installed_at) VALUES (?, ?, ?, 'online', ?)",
            (site_id, sku, capacity_gb, iso(now_utc())),
        )
        return cur.lastrowid or 0

    def list_tape_libraries(self, site_id: int | None = None) -> list[dict]:
        if site_id is not None:
            rows = self._conn.execute(
                "SELECT id, site_id, sku, capacity_gb, status, installed_at "
                "FROM tape_libraries WHERE site_id = ? ORDER BY id",
                (site_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, site_id, sku, capacity_gb, status, installed_at "
                "FROM tape_libraries ORDER BY id"
            ).fetchall()
        return [
            {
                "id": r[0], "site_id": r[1], "sku": r[2],
                "capacity_gb": float(r[3]), "status": r[4],
                "installed_at": r[5],
            } for r in rows
        ]

    def sum_site_tape_libraries_gb(self, site_id: int) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(capacity_gb), 0) FROM tape_libraries "
            "WHERE site_id = ? AND status = 'online'",
            (site_id,),
        ).fetchone()
        return float(row[0]) if row else 0.0

    def sum_site_storage_used_gb(self, site_id: int) -> float:
        """Items currently held on working storage at this site
        (quarantined / analyzing / analyzed / archiving states)."""
        row = self._conn.execute(
            "SELECT COALESCE(SUM(size_gb), 0) FROM items "
            "WHERE current_site_id = ? AND state IN "
            "('quarantined', 'analyzing', 'analyzed', 'archiving')",
            (site_id,),
        ).fetchone()
        return float(row[0]) if row else 0.0

    def sum_site_tape_used_gb(self, site_id: int) -> float:
        """Items in archived state living at this site."""
        row = self._conn.execute(
            "SELECT COALESCE(SUM(size_gb), 0) FROM items "
            "WHERE current_site_id = ? AND state = 'archived'",
            (site_id,),
        ).fetchone()
        return float(row[0]) if row else 0.0

    def update_host_specs(self, host_id: int, specs: dict) -> None:
        self._conn.execute(
            "UPDATE hosts SET specs = ? WHERE id = ?",
            (json.dumps(specs), host_id),
        )

    # --- pumps (dewatering for underground sites) ---------------------

    def create_pump(
        self, site_id: int, sku: str, capacity: str, redundant: bool
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO pumps (site_id, sku, capacity, redundant, status, "
            "installed_at) VALUES (?, ?, ?, ?, 'online', ?)",
            (site_id, sku, capacity, 1 if redundant else 0, iso(now_utc())),
        )
        return cur.lastrowid or 0

    def list_pumps(self, site_id: int | None = None) -> list[dict]:
        if site_id is not None:
            rows = self._conn.execute(
                "SELECT id, site_id, sku, capacity, redundant, status, installed_at "
                "FROM pumps WHERE site_id = ? ORDER BY id",
                (site_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, site_id, sku, capacity, redundant, status, installed_at "
                "FROM pumps ORDER BY id"
            ).fetchall()
        return [
            {
                "id": r[0], "site_id": r[1], "sku": r[2],
                "capacity": r[3], "redundant": bool(r[4]),
                "status": r[5], "installed_at": r[6],
            } for r in rows
        ]

    def count_site_pumps(self, site_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM pumps WHERE site_id = ? AND status = 'online'",
            (site_id,),
        ).fetchone()
        return int(row[0]) if row else 0

    # --- cooling units (site-level cooling capacity additions) ---------

    def create_cooling_unit(
        self,
        site_id: int,
        sku: str,
        kw_rating: int,
        cooling_type: str,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO cooling_units (site_id, sku, kw_rating, cooling_type, "
            "status, installed_at) VALUES (?, ?, ?, ?, 'online', ?)",
            (site_id, sku, kw_rating, cooling_type, iso(now_utc())),
        )
        return cur.lastrowid or 0

    def list_cooling_units(self, site_id: int | None = None) -> list[dict]:
        if site_id is not None:
            rows = self._conn.execute(
                "SELECT id, site_id, sku, kw_rating, cooling_type, status, "
                "installed_at FROM cooling_units WHERE site_id = ? ORDER BY id",
                (site_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, site_id, sku, kw_rating, cooling_type, status, "
                "installed_at FROM cooling_units ORDER BY id"
            ).fetchall()
        return [
            {
                "id": r[0], "site_id": r[1], "sku": r[2],
                "kw_rating": r[3], "cooling_type": r[4],
                "status": r[5], "installed_at": r[6],
            } for r in rows
        ]

    def sum_site_cooling_units_kw(self, site_id: int) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(kw_rating), 0) FROM cooling_units "
            "WHERE site_id = ? AND status = 'online'",
            (site_id,),
        ).fetchone()
        return int(row[0]) if row else 0

    # --- reset (wipes all gameplay state; keeps schema) ---------------

    RESET_TABLES = (
        "cooling_units",
        "pumps",
        "tape_libraries",
        "storage_arrays",
        "outages",
        "site_resilience",
        "power_plants",
        "submarines",
        "site_ground_station",
        "satellites",
        "ships",
        "site_port",
        "aircraft",
        "site_airfield",
        "playbooks",
        "site_encryption",
        "site_network",
        "contracts",
        "enrollments",
        "purchases",
        "incidents",
        "mistakes",
        "staff",
        "funding",
        "items",
        "tape_drives",
        "vms",
        "hosts",
        "site_capacity",
        "sites",
        "scheduled",
        "events",
    )

    def reset_state(self) -> None:
        """Truncate every gameplay table — campaign is gone. Schema stays."""
        for table in self.RESET_TABLES:
            self._conn.execute(f"DELETE FROM {table}")
        # Reset AUTOINCREMENT so IDs start from 1 again in the new campaign.
        self._conn.execute(
            "DELETE FROM sqlite_sequence WHERE name IN ("
            + ",".join(f"'{t}'" for t in self.RESET_TABLES)
            + ")"
        )

    # ------------------------------------------------------------------

    def close(self) -> None:
        self._conn.close()
