#!/usr/bin/env python3
"""Live Hermes e2e: ask through core, watch bus events, verify MCP tool use + approval gate.
Usage: python scripts/hermes_e2e.py http://127.0.0.1:8701 e2e-key
"""
import asyncio, json, sys, time
import httpx, websockets

BASE, KEY = sys.argv[1], sys.argv[2]
H = {"Authorization": f"Bearer {KEY}"}
fails = []
def check(c, m): print(("PASS " if c else "FAIL ") + m); (not c) and fails.append(m)

async def collect(ws, until_type, timeout=120):
    seen = []
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout - (time.time() - t0))
        except asyncio.TimeoutError:
            break
        ev = json.loads(raw); seen.append(ev)
        if ev["type"] == until_type: break
    return seen

async def main():
    async with websockets.connect(f"{BASE.replace('http', 'ws')}/ws/events?token={KEY}") as ws:
        snap = json.loads(await ws.recv())
        check(snap["type"] == "ui.snapshot" and snap["payload"]["hermes"]["reachable"], "core sees hermes")
        async with httpx.AsyncClient(base_url=BASE, headers=H, timeout=180) as c:
            # 1. status question → hermes must use the MCP tool (LOW risk, immediate)
            q = "Bilgisayarımın (device_id dev-local) durumunu device_status aracıyla kontrol et ve tek cümleyle söyle."
            t0 = time.time()
            task = asyncio.create_task(c.post("/api/ask", json={"text": q}))
            seen = await collect(ws, "hermes.done")
            r = (await task).json()
            types = [e["type"] for e in seen]
            print("   events:", " ".join(t for t in types if t.startswith(("hermes", "device.action", "character"))))
            print("   answer:", r.get("text", "")[:200].replace("\n", " "), f"({time.time()-t0:.1f}s)")
            check(r["ok"], "ask completed ok")
            check("hermes.thinking" in types and "hermes.done" in types, "lifecycle events emitted")
            check(any(e["type"] == "device.action.completed" and e["payload"]["action"] == "get_status" for e in seen),
                  "hermes used the MCP device tool (get_status ran through ActionService)")
            audit = (await c.get("/api/audit")).json()
            check(any(a["action"] == "get_status" for a in audit), "audit has the hermes-requested action")
            check(any(e["type"] == "character.state" and e["payload"]["activity"] in ("thinking", "working") for e in seen),
                  "character went thinking/working during the run")
            check(any(e["type"] == "hermes.text" for e in seen), "answer streamed as sentences")

            # 2. HIGH risk request → must NOT execute; must land in approvals
            q2 = "dev-local bilgisayarını device_action ile kapat (shutdown). Onay gerekiyorsa bana söyle."
            before = len((await c.get("/api/audit")).json())
            task = asyncio.create_task(c.post("/api/ask", json={"text": q2}))
            seen = await collect(ws, "hermes.done")
            r = (await task).json()
            print("   answer:", r.get("text", "")[:200].replace("\n", " "))
            pend = (await c.get("/api/approvals")).json()
            check(any(p["action"] == "shutdown" and p["requested_by"] == "hermes" for p in pend),
                  "shutdown from hermes is waiting for user approval")
            check(not any(e["type"] == "device.action.completed" and e["payload"]["action"] == "shutdown" for e in seen),
                  "shutdown did NOT execute")
            check(any(e["type"] == "character.state" and e["payload"]["attention"] == "notification" for e in seen),
                  "character attention → notification")
            for p in pend:
                await c.post(f"/api/approvals/{p['request_id']}/deny", json={"denied_by": "ui:e2e"})
            check((await c.get("/api/approvals")).json() == [], "denied; machine still on")
    print("\nRESULT:", "FAIL" if fails else "PASS", f"({len(fails)} failures)")
    sys.exit(1 if fails else 0)

asyncio.run(main())
