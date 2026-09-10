"""HermesBridge — Hermes is the brain; this is the only place that talks to it.

    ask(text, character) → POST /v1/runs {input, session_id, instructions}
                         → GET  /v1/runs/{id}/events (SSE)
                         → bus: hermes.thinking, hermes.tool.started/completed/failed,
                                hermes.speaking, hermes.text {text}, hermes.approval.request,
                                hermes.error, hermes.unavailable, hermes.done

Character context is passed per request via `instructions` (never persisted in Hermes).
The bridge never blocks the caller on Hermes being down: failures become events + result.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from httpx_sse import aconnect_sse

from heren_core.bus import EventBus

log = logging.getLogger("heren.hermes")

_ABBREV = {"dr", "prof", "mr", "mrs", "ms", "vs", "vb", "örn", "no", "sn", "st"}
_END = re.compile(r"([.!?…]+)(\s+|$)")


def sentences(buf: str) -> tuple[list[str], str]:
    """Split completed sentences off `buf`; return (done, remainder)."""
    done: list[str] = []
    start = 0
    for m in _END.finditer(buf):
        end = m.end(1)
        if m.group(2) == "" and end == len(buf):
            break  # sentence may still be growing (no trailing space yet)
        before = buf[start:end]
        word = re.split(r"\s", before.strip())[-1].rstrip(".!?…").lower()
        prev = buf[end - 2] if end >= 2 else ""
        if word in _ABBREV or (m.group(1) == "." and prev.isdigit() and buf[end:end + 1].isdigit()):
            continue
        done.append(before.strip())
        start = m.end()
    return done, buf[start:]


@dataclass
class AskResult:
    ok: bool
    text: str = ""
    error: str | None = None
    run_id: str | None = None


INSTRUCTIONS_TEMPLATE = (
    "You are Heren, the living assistant character of a home server. Answer in {language}. "
    "Current time {time}. Your presentation state: activity={activity}, mood={mood}, energy={energy:.2f}. "
    "Let the mood colour tone and length only; never change facts, results or errors. "
    "To control computers use ONLY the device_list / device_status / device_action tools; "
    "never use terminal or ssh for device control. High-risk actions require the user's approval "
    "in the dashboard — say so and wait, do not retry."
)


class HermesBridge:
    def __init__(self, *, bus: EventBus, endpoint: str, api_key: str | None,
                 client_factory: Callable[[], httpx.AsyncClient] | None = None,
                 session_id: str = "heren", language: str = "Turkish",
                 request_timeout_s: float = 600.0) -> None:
        self.bus = bus
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.session_id = session_id
        self.language = language
        self.request_timeout_s = request_timeout_s
        self.client_factory = client_factory or (lambda: httpx.AsyncClient(base_url=self.endpoint, timeout=30))
        self._lock = asyncio.Lock()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key or ''}"}

    def instructions(self, character: dict[str, Any] | None) -> str:
        c = dict(character or {})
        c.setdefault("time", time.strftime("%H:%M"))
        c.setdefault("activity", "idle"); c.setdefault("mood", "neutral"); c.setdefault("energy", 1.0)
        return INSTRUCTIONS_TEMPLATE.format(language=self.language, **c)

    async def healthy(self) -> bool:
        try:
            async with self.client_factory() as c:
                r = await c.get("/health", timeout=3)
                return r.status_code == 200
        except Exception:
            return False

    async def respond_approval(self, run_id: str, approval_id: str, *, approve: bool) -> None:
        async with self.client_factory() as c:
            await c.post(f"/v1/runs/{run_id}/approval", headers=self._headers(),
                         json={"approval_id": approval_id, "choice": "approve" if approve else "deny"})

    # ------------------------------------------------------------ main entry

    async def ask(self, text: str, character: dict[str, Any] | None = None) -> AskResult:
        async with self._lock:  # one run per session at a time
            return await self._ask(text, character)

    async def _ask(self, text: str, character: dict[str, Any] | None) -> AskResult:
        await self.bus.emit("hermes.thinking", input=text)
        run_id: str | None = None
        try:
            async with self.client_factory() as c:
                r = await c.post("/v1/runs", headers=self._headers(), json={
                    "input": text, "session_id": self.session_id,
                    "instructions": self.instructions(character),
                })
                if r.status_code not in (200, 202):
                    return await self._fail(f"hermes /v1/runs → {r.status_code}: {r.text[:200]}")
                run_id = r.json()["run_id"]
                return await self._stream(c, run_id)
        except (httpx.HTTPError, OSError) as e:
            await self.bus.emit("hermes.unavailable", error=str(e))
            return await self._fail(f"hermes unreachable: {e}", run_id)

    async def _stream(self, c: httpx.AsyncClient, run_id: str) -> AskResult:
        buf = ""
        full = ""
        speaking = False
        async with aconnect_sse(c, "GET", f"/v1/runs/{run_id}/events", headers=self._headers(),
                                timeout=self.request_timeout_s) as es:
            async for sse in es.aiter_sse():
                if not sse.data:
                    continue
                try:
                    ev = json.loads(sse.data)
                except json.JSONDecodeError:
                    continue
                kind = ev.get("event")
                if kind == "tool.started":
                    await self.bus.emit("hermes.tool.started", run_id=run_id, tool=ev.get("tool"),
                                        preview=ev.get("preview"))
                elif kind == "tool.completed":
                    topic = "hermes.tool.failed" if ev.get("error") else "hermes.tool.completed"
                    await self.bus.emit(topic, run_id=run_id, tool=ev.get("tool"), duration=ev.get("duration"))
                elif kind == "message.delta":
                    delta = ev.get("delta") or ""
                    if not speaking:
                        speaking = True
                        await self.bus.emit("hermes.speaking", run_id=run_id)
                    full += delta
                    buf += delta
                    done, buf = sentences(buf)
                    for s in done:
                        await self.bus.emit("hermes.text", run_id=run_id, text=s)
                elif kind == "approval.request":
                    await self.bus.emit("hermes.approval.request", run_id=run_id, **{
                        k: v for k, v in ev.items() if k not in ("event", "run_id", "timestamp")})
                elif kind == "run.completed":
                    output = ev.get("output") or full
                    if not speaking and output:
                        await self.bus.emit("hermes.speaking", run_id=run_id)
                    tail = output[len(full):] if output.startswith(full) else ""
                    buf += tail
                    done, buf = sentences(buf)
                    for s in done + ([buf.strip()] if buf.strip() else []):
                        await self.bus.emit("hermes.text", run_id=run_id, text=s)
                    await self.bus.emit("hermes.done", run_id=run_id, ok=True)
                    return AskResult(ok=True, text=output, run_id=run_id)
                elif kind in ("run.failed", "run.cancelled"):
                    return await self._fail(ev.get("error") or kind, run_id)
        return await self._fail("hermes stream ended without completion", run_id)

    async def _fail(self, error: str, run_id: str | None = None) -> AskResult:
        log.warning("hermes ask failed: %s", error)
        await self.bus.emit("hermes.error", run_id=run_id, error=error)
        await self.bus.emit("hermes.done", run_id=run_id, ok=False)
        return AskResult(ok=False, error=error, run_id=run_id)
