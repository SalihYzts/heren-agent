#!/usr/bin/env python3
"""Drive the real dashboard in headless Chromium over CDP and verify the HIGH-risk gate.

Usage: python scripts/ui_e2e.py http://127.0.0.1:8701 e2e-key 9333
Prints PASS/FAIL lines; screenshots in /tmp/heren-shots. Exit 1 on any failure.
Assumes: core running with the built UI, a Go agent paired as device "dev-local".
"""
import asyncio, base64, json, os, subprocess, sys, time, urllib.request

BASE, KEY, PORT = sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "9333"
OUT = "/tmp/heren-shots"; os.makedirs(OUT, exist_ok=True)
CHROME = os.path.expanduser("~/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome")
import websockets

fails: list[str] = []
def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg); (not cond) and fails.append(msg)

async def main():
    proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={PORT}", "--no-sandbox",
                             "--disable-gpu", "--window-size=1440,900", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try: tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json")); break
            except Exception: await asyncio.sleep(0.2)
        page = next(t for t in tabs if t["type"] == "page")
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=2**26) as ws:
            _id = [0]; console: list[str] = []
            async def send(method, **params):
                _id[0] += 1
                await ws.send(json.dumps({"id": _id[0], "method": method, "params": params}))
                while True:
                    m = json.loads(await ws.recv())
                    if m.get("method") == "Runtime.exceptionThrown":
                        console.append(m["params"]["exceptionDetails"].get("text", "exception"))
                    if m.get("method") == "Runtime.consoleAPICalled" and m["params"]["type"] == "error":
                        console.append(" ".join(str(a.get("value", a.get("description", ""))) for a in m["params"]["args"]))
                    if m.get("id") == _id[0]: return m.get("result", m)
            async def js(expr):
                r = await send("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
                if "exceptionDetails" in r: raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", r))
                return r["result"].get("value")
            async def shot(name):
                r = await send("Page.captureScreenshot", format="png")
                p = f"{OUT}/{name}.png"; open(p, "wb").write(base64.b64decode(r["data"])); print("   shot", p)
            async def wait_for(expr, timeout=8):
                t0 = time.time()
                while time.time() - t0 < timeout:
                    if await js(expr): return True
                    await asyncio.sleep(0.15)
                return False
            async def click(sel_or_expr):
                # find element by CSS or by button text, dispatch a real click
                return await js(f"""(() => {{
                    const q = {json.dumps(sel_or_expr)};
                    let el = null; try {{ el = document.querySelector(q); }} catch (e) {{}}
                    if (!el) el = [...document.querySelectorAll('button')].find(b => b.textContent.trim().toLowerCase() === q.toLowerCase());
                    if (!el) return false; el.click(); return true; }})()""")

            await send("Runtime.enable"); await send("Page.enable")
            await send("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False)
            await send("Page.navigate", url=BASE + "/"); await asyncio.sleep(1.0)

            # ---- login
            check(await wait_for("!!document.querySelector('input[type=password]')"), "login screen renders")
            await shot("01-login")
            await js("(() => { const i = document.querySelector('input[type=password]'); const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set; s.call(i,'wrong-key'); i.dispatchEvent(new Event('input',{bubbles:true})); })()")
            await click("button[type=submit]")
            check(await wait_for("document.body.innerText.includes('geçersiz anahtar')"), "wrong key is rejected with a message")
            await js(f"(() => {{ const i = document.querySelector('input[type=password]'); const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set; s.call(i,{json.dumps(KEY)}); i.dispatchEvent(new Event('input',{{bubbles:true}})); }})()")
            await click("button[type=submit]")
            check(await wait_for("!!document.querySelector('.topbar')"), "correct key opens the dashboard")
            check(await wait_for("document.body.innerText.includes('core bağlı')"), "event stream connects (status bar)")

            # ---- pairing code from the UI, then start the real Go agent with it
            await click("+ Cihaz eşle")
            check(await wait_for("!!document.querySelector('[data-testid=pairing-code]')"), "pairing modal shows a code")
            code = await js("document.querySelector('[data-testid=pairing-code]').textContent.trim()")
            check(code.isdigit() and len(code) == 6, f"pairing code is 6 digits ({code})")
            await shot("02-pairing")
            await click("Kapat")
            agent_cfg = "/tmp/heren-e2e/agent.yaml"
            open(agent_cfg, "w").write(f"core_url: {BASE.replace('http', 'ws')}/ws/agent\ndevice_id: dev-local\nname: DEV PC (Go)\nkey_file: /tmp/heren-e2e/go-agent.key\napproved_commands:\n  say-hi: ['echo', 'hi']\n")
            agent = subprocess.Popen([os.path.join(os.path.dirname(__file__), "../../../agents/device-agent/dist/heren-agent-linux-amd64"),
                                      "--config", agent_cfg, "--pair", code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                check(await wait_for("[...document.querySelectorAll('.device')].some(d => d.textContent.includes('DEV PC (Go)') && d.querySelector('.status.online'))", 10),
                      "paired agent appears as a live device card (no reload)")
                check(await wait_for("!![...document.querySelectorAll('.meter')].find(m => m.textContent.includes('%') && !m.textContent.includes('—'))", 15),
                      "live metrics arrive over the event stream")
                await shot("03-device-online")

                # ---- LOW action from the card
                await click("get status")
                check(await wait_for("document.body.innerText.includes('get_status: tamam')"), "LOW action runs immediately (toast)")
                check(await wait_for("!![...document.querySelectorAll('.row')].find(r => r.textContent.includes('get_status') && r.textContent.includes('completed'))"),
                      "activity log shows the completed action")

                # ---- boot entries → next-boot buttons
                await click("get boot entries")
                check(await wait_for("document.body.innerText.includes('NEXT BOOT')", 10), "boot entries render as switch buttons")
                await shot("04-boot-entries")

                # ---- character (phase 4): live state over the event stream, fixed ASCII box
                check(await wait_for("!!document.querySelector('[data-testid=character-panel]')"), "character panel renders")
                pre_ok = await js("(() => { const p = document.querySelector('[data-testid=ascii-frame]'); const cs = getComputedStyle(p); return p.tagName === 'PRE' && cs.whiteSpace === 'pre' && /mono/i.test(cs.fontFamily); })()")
                check(pre_ok, "ASCII frame is a <pre>, white-space: pre, monospace font")
                box0 = await js("(() => { const r = document.querySelector('[data-testid=ascii-frame]').getBoundingClientRect(); return [r.width, r.height]; })()")
                check(await js("document.querySelector('[data-testid=ascii-frame]').dataset.activity") == "idle", "character starts idle")
                await click("[data-testid=character-panel] .character-b")
                check(await wait_for("document.querySelector('[data-testid=ascii-frame]').dataset.activity === 'listening'", 5), "touch → listening (live via character.state)")
                await asyncio.sleep(0.5)
                box1 = await js("(() => { const r = document.querySelector('[data-testid=ascii-frame]').getBoundingClientRect(); return [r.width, r.height]; })()")
                check(box0 == box1, f"ASCII box size is stable across states ({box0} == {box1})")
                fa = await js("document.querySelector('[data-testid=ascii-frame]').textContent")
                await asyncio.sleep(0.45)
                fb = await js("document.querySelector('[data-testid=ascii-frame]').textContent")
                check(fa != fb, "listening animation cycles frames")
                check(await js("document.querySelector('[data-testid=ascii-frame]').dataset.fallback") is None, "listening uses real art, not fallback")
                await shot("10-character-listening")
                check(await wait_for("document.querySelector('[data-testid=ascii-frame]').dataset.activity === 'idle'", 12), "listening times out back to idle")

                # ---- HIGH action must wait for approval and must NOT run
                before = json.loads(await js(f"fetch('/api/audit',{{headers:{{Authorization:'Bearer {KEY}'}}}}).then(r=>r.json()).then(j=>JSON.stringify(j.length))"))
                await click("shutdown")
                check(await wait_for("document.body.innerText.includes('shutdown: onay bekliyor')"), "HIGH action reports awaiting approval")
                check(await wait_for("!!document.querySelector('.approval') && document.querySelector('.approval').textContent.includes('shutdown')"), "approval card appears in the side panel")
                await shot("05-approval-pending")
                check(await wait_for("document.body.innerText.includes('ATTN notification')", 5), "character attention → notification while approval pending")
                await asyncio.sleep(1.0)
                after = json.loads(await js(f"fetch('/api/audit',{{headers:{{Authorization:'Bearer {KEY}'}}}}).then(r=>r.json()).then(j=>JSON.stringify(j.length))"))
                check(after == before, "nothing was executed while approval is pending (audit unchanged)")
                await click("Reddet")
                check(await wait_for("!document.querySelector('.approval')"), "deny removes the approval card")
                check(await wait_for("document.body.innerText.includes('ATTN none')", 5), "character attention returns to none after resolve")
                check(await wait_for("!![...document.querySelectorAll('.row')].find(r => r.textContent.includes('shutdown') && r.textContent.includes('denied'))"), "activity shows shutdown denied")
                await shot("06-denied")

                # ---- HIGH via API from 'hermes' shows up live, approve from UI runs it (non-destructive: set_next_boot needs an entry; use 'lock' is medium... use sleep? no) → use restart_service? medium. Use shutdown again but approve? destructive. So approve a set_next_boot to a bogus entry: agent refuses safely.
                await js(f"fetch('/api/actions',{{method:'POST',headers:{{Authorization:'Bearer {KEY}','Content-Type':'application/json'}},body:JSON.stringify({{device_id:'dev-local',action:'set_next_boot',params:{{entry:'ZZZZ'}},requested_by:'hermes'}})}})")
                check(await wait_for("!!document.querySelector('.approval') && document.querySelector('.approval').textContent.includes('hermes')"), "request from hermes appears live for the user to decide")
                await click("Onayla")
                check(await wait_for("!![...document.querySelectorAll('.row')].find(r => r.textContent.includes('set_next_boot') && r.textContent.includes('failed'))"),
                      "approved action reached the agent (agent safely refused unknown entry)")
                await shot("07-approved-run")

                # ---- audit tab
                await click("Denetim")
                check(await wait_for("!![...document.querySelectorAll('.row')].find(r => r.textContent.includes('by ui:dashboard'))"), "audit tab shows approver identity")
                await shot("08-audit")

                # ---- agent goes away → card flips offline, buttons disabled
                agent.terminate(); agent.wait(timeout=5)
                check(await wait_for("!!document.querySelector('.device .status.offline')", 10), "agent loss flips card to offline live")
                check(await js("document.querySelector('.device button').disabled"), "offline device buttons are disabled")
                await shot("09-offline")
            finally:
                if agent.poll() is None: agent.terminate()

            check(not console, f"no console errors ({console[:3]})")
    finally:
        proc.terminate()

asyncio.run(main())
print("\nRESULT:", "FAIL" if fails else "PASS", f"({len(fails)} failures)")
sys.exit(1 if fails else 0)
