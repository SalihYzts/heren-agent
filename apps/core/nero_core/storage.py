"""SQLite persistence (aiosqlite). One file, WAL mode, schema created on open."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import aiosqlite

from nero_core.protocol import ActionRequest, ActionStatus, Device, DeviceStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    device_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    platform    TEXT NOT NULL,
    public_key  TEXT NOT NULL,
    status      TEXT NOT NULL,
    last_seen   REAL,
    capabilities TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS actions (
    request_id   TEXT PRIMARY KEY,
    device_id    TEXT NOT NULL,
    action       TEXT NOT NULL,
    params       TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    created_at   REAL NOT NULL,
    status       TEXT NOT NULL,
    approved_by  TEXT
);
CREATE INDEX IF NOT EXISTS actions_status ON actions(status);
CREATE TABLE IF NOT EXISTS audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL NOT NULL,
    request_id  TEXT NOT NULL,
    device_id   TEXT NOT NULL,
    action      TEXT NOT NULL,
    risk        TEXT NOT NULL,
    approved_by TEXT,
    result      TEXT NOT NULL,
    duration_ms INTEGER,
    error       TEXT,
    params      TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_SECRET_KEY_RE = re.compile(r"(pass|secret|token|key|credential|auth)", re.IGNORECASE)


def redact(params: dict[str, Any]) -> dict[str, Any]:
    return {k: ("[redacted]" if _SECRET_KEY_RE.search(k) else v) for k, v in params.items()}


class Storage:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "Storage not opened"
        return self._db

    # ----------------------------------------------------------------- devices

    async def upsert_device(self, d: Device) -> None:
        await self.db.execute(
            """INSERT INTO devices(device_id,name,platform,public_key,status,last_seen,capabilities)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(device_id) DO UPDATE SET name=excluded.name, platform=excluded.platform,
               public_key=excluded.public_key, capabilities=excluded.capabilities""",
            (d.device_id, d.name, d.platform, d.public_key, d.status, d.last_seen,
             json.dumps(d.capabilities)),
        )
        await self.db.commit()

    async def get_device(self, device_id: str) -> Device | None:
        cur = await self.db.execute("SELECT * FROM devices WHERE device_id=?", (device_id,))
        row = await cur.fetchone()
        return self._row_to_device(row) if row else None

    async def list_devices(self) -> list[Device]:
        cur = await self.db.execute("SELECT * FROM devices ORDER BY name")
        return [self._row_to_device(r) for r in await cur.fetchall()]

    async def set_device_status(self, device_id: str, status: DeviceStatus,
                                last_seen: float | None = None) -> None:
        await self.db.execute(
            "UPDATE devices SET status=?, last_seen=COALESCE(?, last_seen) WHERE device_id=?",
            (status, last_seen, device_id),
        )
        await self.db.commit()

    @staticmethod
    def _row_to_device(r: aiosqlite.Row) -> Device:
        return Device(
            device_id=r["device_id"], name=r["name"], platform=r["platform"],
            public_key=r["public_key"], status=DeviceStatus(r["status"]),
            last_seen=r["last_seen"], capabilities=json.loads(r["capabilities"]),
        )

    # ----------------------------------------------------------------- actions

    async def save_action(self, a: ActionRequest) -> None:
        await self.db.execute(
            """INSERT OR REPLACE INTO actions(request_id,device_id,action,params,requested_by,
               created_at,status,approved_by) VALUES(?,?,?,?,?,?,?,?)""",
            (a.request_id, a.device_id, a.action, json.dumps(a.params), a.requested_by,
             a.created_at, a.status, a.approved_by),
        )
        await self.db.commit()

    async def get_action(self, request_id: str) -> ActionRequest | None:
        cur = await self.db.execute("SELECT * FROM actions WHERE request_id=?", (request_id,))
        row = await cur.fetchone()
        return self._row_to_action(row) if row else None

    async def update_action_status(self, request_id: str, status: ActionStatus,
                                   approved_by: str | None = None) -> None:
        await self.db.execute(
            "UPDATE actions SET status=?, approved_by=COALESCE(?, approved_by) WHERE request_id=?",
            (status, approved_by, request_id),
        )
        await self.db.commit()

    async def list_actions(self, status: ActionStatus | None = None, limit: int = 100) -> list[ActionRequest]:
        if status is None:
            cur = await self.db.execute("SELECT * FROM actions ORDER BY created_at DESC LIMIT ?", (limit,))
        else:
            cur = await self.db.execute(
                "SELECT * FROM actions WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit))
        return [self._row_to_action(r) for r in await cur.fetchall()]

    @staticmethod
    def _row_to_action(r: aiosqlite.Row) -> ActionRequest:
        return ActionRequest(
            request_id=r["request_id"], device_id=r["device_id"], action=r["action"],
            params=json.loads(r["params"]), requested_by=r["requested_by"],
            created_at=r["created_at"], status=ActionStatus(r["status"]), approved_by=r["approved_by"],
        )

    # ----------------------------------------------------------------- audit

    async def audit(self, request_id: str, device_id: str, action: str, *, risk: str,
                    approved_by: str | None, result: str, duration_ms: int | None,
                    error: str | None = None, params: dict[str, Any] | None = None) -> None:
        await self.db.execute(
            """INSERT INTO audit(ts,request_id,device_id,action,risk,approved_by,result,duration_ms,error,params)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (time.time(), request_id, device_id, action, risk, approved_by, result, duration_ms,
             error, json.dumps(redact(params or {}))),
        )
        await self.db.commit()

    async def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        cur = await self.db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))
        rows = []
        for r in await cur.fetchall():
            d = dict(r)
            d["params"] = json.loads(d["params"])
            rows.append(d)
        return rows

    # ----------------------------------------------------------------- settings

    async def get_setting(self, key: str, default: str | None = None) -> str | None:
        cur = await self.db.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        await self.db.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await self.db.commit()
