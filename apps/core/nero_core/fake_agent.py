"""Reference/fake device agent in Python.

Mirrors what the Go agent will do: pair, sign envelopes, heartbeat, answer actions.
Useful for development without a real agent and as the protocol conformance reference.

    python -m nero_core.fake_agent --core ws://127.0.0.1:8700/ws/agent --pair 123456
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import platform
import time
from pathlib import Path

import websockets

from nero_core.protocol import Envelope
from nero_core.security import KeyPair, sign, verify

log = logging.getLogger("nero.fake_agent")


class FakeAgent:
    def __init__(self, core_url: str, device_id: str, name: str, key_file: Path,
                 pairing_code: str | None = None) -> None:
        self.core_url = core_url
        self.device_id = device_id
        self.name = name
        self.pairing_code = pairing_code
        self.kp = self._load_or_create(key_file)
        self.core_public_key: str | None = None
        self.started = time.time()

    @staticmethod
    def _load_or_create(path: Path) -> KeyPair:
        if path.exists():
            return KeyPair.from_seed_hex(path.read_text().strip())
        kp = KeyPair.generate()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(kp.seed_hex)
        os.chmod(path, 0o600)
        return kp

    # ------------------------------------------------------------ actions

    async def run_action(self, action: str, params: dict) -> dict:
        if action == "get_status":
            return {"status": "completed", "output": {"uptime_s": int(time.time() - self.started),
                                                      "platform": platform.system().lower()}}
        if action == "get_metrics":
            load = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
            return {"status": "completed", "output": {"load1": load}}
        if action in ("shutdown", "restart", "sleep", "lock", "launch_app", "stop_app",
                      "restart_service", "set_next_boot", "run_approved_command", "wake"):
            log.info("SIMULATED %s %s", action, params)
            return {"status": "completed", "output": {"simulated": True, "action": action}}
        return {"status": "failed", "error": f"unsupported action {action}"}

    # ------------------------------------------------------------ loop

    async def run_forever(self) -> None:
        backoff = 1.0
        while True:
            try:
                await self._session()
                backoff = 1.0
            except (OSError, websockets.exceptions.WebSocketException) as e:
                log.warning("connection lost: %s — retry in %.0fs", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _session(self) -> None:
        async with websockets.connect(self.core_url) as ws:
            hello = {"type": "hello", "device_id": self.device_id, "name": self.name,
                     "platform": platform.system().lower(), "public_key": self.kp.public_key_hex,
                     "capabilities": ["get_status", "get_metrics", "shutdown", "restart", "launch_app"]}
            if self.pairing_code:
                hello["pairing_code"] = self.pairing_code
            await ws.send(json.dumps(hello))
            welcome = json.loads(await ws.recv())
            if welcome.get("type") != "welcome":
                raise RuntimeError(f"unexpected: {welcome}")
            self.core_public_key = welcome["core_public_key"]
            self.pairing_code = None  # single use
            interval = float(welcome.get("heartbeat_interval_s", 10))
            log.info("paired/connected to core; heartbeat every %.0fs", interval)

            hb = asyncio.create_task(self._heartbeat(ws, interval))
            try:
                async for raw in ws:
                    await self._on_message(ws, json.loads(raw))
            finally:
                hb.cancel()

    async def _heartbeat(self, ws, interval: float) -> None:
        while True:
            await self._send(ws, "heartbeat", cpu=os.getloadavg()[0] if hasattr(os, "getloadavg") else 0)
            await asyncio.sleep(interval)

    async def _on_message(self, ws, data: dict) -> None:
        if data.get("type") == "error":
            log.error("core error: %s", data.get("reason"))
            return
        env = Envelope.model_validate(data)
        verify(env, self.core_public_key or "")  # pin core key
        if env.type == "action.request":
            p = env.payload
            t0 = time.time()
            result = await self.run_action(p["action"], p.get("params", {}))
            await self._send(ws, "action.result", request_id=p["request_id"],
                             duration_ms=int((time.time() - t0) * 1000), **result)

    async def _send(self, ws, type_: str, **payload) -> None:
        env = sign(Envelope(device_id=self.device_id, type=type_, payload=payload), self.kp)
        await ws.send(env.model_dump_json())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", default="ws://127.0.0.1:8700/ws/agent")
    ap.add_argument("--id", default=f"fake-{platform.node()}")
    ap.add_argument("--name", default=platform.node())
    ap.add_argument("--pair", default=None, help="one-time pairing code from the dashboard")
    ap.add_argument("--key-file", default=Path.home() / ".nero" / "agent.key")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(FakeAgent(args.core, args.id, args.name, Path(args.key_file), args.pair).run_forever())


if __name__ == "__main__":
    main()
