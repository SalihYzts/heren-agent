"""MCP server — the only way Hermes controls devices.

Tools: device_list, device_status, device_action. Every action goes through
ActionService.submit(requested_by="hermes"), so the permission engine applies:
HIGH risk returns awaiting_approval and the user decides in the dashboard.

Mounted at /mcp (streamable HTTP). Auth: Bearer <mcp_key> (separate from the UI key).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from heren_core.actions import ActionService
from heren_core.protocol import ActionRequest, ActionStatus, RiskLevel, risk_of
from heren_core.storage import Storage

log = logging.getLogger("heren.mcp")


def build_mcp_server(*, store: Storage, actions: ActionService) -> MCPServer:
    srv = MCPServer(
        name="heren-devices",
        instructions=(
            "Control the user's computers through Heren. Use device_list first to learn ids and "
            "capabilities. High-risk actions (shutdown, restart, sleep, set_next_boot) return "
            "awaiting_approval — tell the user to approve in the dashboard; do not retry."
        ),
    )

    @srv.tool(name="device_list", description="List registered devices with online status and capabilities.")
    async def device_list() -> str:
        return json.dumps([d.model_dump() for d in await store.list_devices()], ensure_ascii=False)

    @srv.tool(name="device_status", description="Run get_status on a device (LOW risk, immediate).")
    async def device_status(device_id: str) -> str:
        return await _run(device_id, "get_status", {})

    @srv.tool(name="device_action",
              description=("Run an action on a device. Actions: get_status, get_metrics, get_boot_entries, lock, "
                           "launch_app{app}, stop_app{app}, restart_service{name}, run_approved_command{command_id}, "
                           "sleep, shutdown, restart, set_next_boot{entry}. HIGH risk ones need user approval."))
    async def device_action(device_id: str, action: str, params: dict[str, Any] | None = None) -> str:
        return await _run(device_id, action, params or {})

    async def _run(device_id: str, action: str, params: dict[str, Any]) -> str:
        if await store.get_device(device_id) is None:
            return json.dumps({"status": "failed", "error": f"unknown device '{device_id}'"})
        try:
            req = ActionRequest(device_id=device_id, action=action, params=params, requested_by="hermes")
        except ValueError as e:
            return json.dumps({"status": "failed", "error": str(e)})
        res = await actions.submit(req)
        out: dict[str, Any] = res.model_dump()
        out["risk"] = risk_of(action)
        if res.status == ActionStatus.AWAITING_APPROVAL:
            out["message"] = ("This action needs the user's approval in the Heren dashboard. "
                              "Tell the user and wait; do not retry.")
        elif risk_of(action) == RiskLevel.CRITICAL:
            out["message"] = "Critical actions are disabled."
        return json.dumps(out, ensure_ascii=False)

    return srv


class BearerGate:
    """ASGI wrapper: require `Authorization: Bearer <key>` before reaching the MCP app."""

    def __init__(self, app: ASGIApp, key: str) -> None:
        self.app = app
        self.key = key

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            req = Request(scope, receive)
            if req.headers.get("authorization") != f"Bearer {self.key}":
                await JSONResponse({"error": "invalid mcp key"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)
