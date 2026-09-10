#!/usr/bin/env python3
"""Drive the conversation panel against the real Hermes and screenshot it.
Usage: python scripts/ui_hermes_e2e.py http://127.0.0.1:8701 e2e-key 9333"""
import asyncio, base64, json, os, subprocess, sys, time, urllib.request
import websockets

BASE, KEY, PORT = sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "9333"
OUT = "/tmp/heren-shots"; os.makedirs(OUT, exist_ok=True)
CHROME = os.path.expanduser("~/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome")
fails = []
def check(c, m): print(("PASS " if c else "FAIL ") + m); (not c) and fails.append(m)

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
            _id = [0]; console = []
            async def send(method, **params):
                _id[0] += 1
                await ws.send(json.dumps({"id": _id[0], "method": method, "params": params}))
                while True:
                    m = json.loads(await ws.recv())
                    if m.get("method") == "Runtime.exceptionThrown": console.append("exception")
                    if m.get("id") == _id[0]: return m.get("result", m)
            async def js(expr):
                r = await send("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
                if "exceptionDetails" in r: raise RuntimeError(r["exceptionDetails"])
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
            async def set_input(sel, val):
                await js(f"(() => {{ const i = document.querySelector({json.dumps(sel)}); const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set; s.call(i,{json.dumps(val)}); i.dispatchEvent(new Event('input',{{bubbles:true}})); }})()")

            await send("Runtime.enable"); await send("Page.enable")
            await send("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False)
            await send("Page.navigate", url=BASE + "/"); await asyncio.sleep(0.8)
            await js(f"sessionStorage.setItem('heren.api_key', {json.dumps(KEY)})")
            await send("Page.navigate", url=BASE + "/"); await asyncio.sleep(1.0)
            check(await wait_for("!!document.querySelector('[data-testid=conversation]')"), "conversation panel renders")
            # voice bar + instrument Audio playback (headless has no output device, but play()/ended fire)
            check(await wait_for("!!document.querySelector('[data-testid=voicebar]')"), "voice bar renders")
            await js("""(() => { window.__audio = []; const P = HTMLMediaElement.prototype.play;
                HTMLMediaElement.prototype.play = function() { window.__audio.push({src: this.src.slice(0, 5), t: performance.now()}); return P.call(this) };
                window.__vstat = []; const el = document.querySelector('[data-testid=voice-status]');
                new MutationObserver(() => window.__vstat.push(el.textContent)).observe(el, { childList: true, characterData: true, subtree: true }); })()""")
            check(await wait_for("document.querySelector('[data-testid=hermes-status]').textContent.includes('hazır')", 10), "status shows hermes ready")
            # record every activity the character passes through (MutationObserver beats polling)
            await js("""(() => { window.__acts = []; const el = document.querySelector('[data-testid=ascii-frame]');
                window.__acts_t = [];
                const mo = new MutationObserver(() => { window.__acts.push(el.dataset.activity); window.__acts_t.push({a: el.dataset.activity, t: performance.now()}) });
                mo.observe(el, { attributes: true, attributeFilter: ['data-activity'] }); })()""")
            await set_input(".conv-input input", "dev-local bilgisayarımın anlık yükünü (get_metrics) device_action ile oku ve söyle")
            await js("document.querySelector('.conv-input button').click()")
            check(await wait_for("!!document.querySelector('.conv-row.user')"), "question appears in conversation")
            check(await wait_for("/düşünüyor|çalışıyor/.test(document.querySelector('[data-testid=hermes-status]').textContent)", 5), "status shows thinking/working")
            await asyncio.sleep(2.0)
            await shot("11-hermes-working")
            check(await wait_for("!!document.querySelector('.conv-row.heren')", 90), "answer row appears")
            acts = await js("JSON.stringify(window.__acts)")
            print("   character activities:", acts)
            check("thinking" in acts, "character went thinking")
            check("working" in acts, "character went working while hermes used the device tool")
            check("speaking" in acts, "character went speaking")
            check(await wait_for("document.querySelector('[data-testid=hermes-status]').textContent.includes('hazır')", 90), "status back to ready")
            ans = await js("document.querySelector('.conv-row.heren .text').textContent")
            print("   answer:", ans[:160])
            check(len(ans) > 10, "answer has content")
            check(await wait_for("document.querySelector('[data-testid=ascii-frame]').dataset.activity === 'idle'", 15), "character back to idle")
            # speech playback: at least one clip played through <audio>, status went 'konuşuyor' and back
            check(await wait_for("window.__audio.length >= 1", 20), "a synthesized clip was handed to <audio>.play()")
            check(await wait_for("document.querySelector('[data-testid=voice-status]').dataset.speaking === '0'", 40), "playback finished (status back to quiet)")
            vs = await js("JSON.stringify(window.__vstat)"); na = await js("window.__audio.length")
            print("   voice status trail:", vs, "clips played:", na)
            check("konuşuyor" in vs, "voice bar showed 'konuşuyor' during playback")
            # the character must not drop to idle before the audio ended: idle transition after last play()
            idle_after_audio = await js("(() => { const a = window.__audio.at(-1)?.t ?? 0; return (window.__acts_t ?? []).some(x => x.a === 'idle' && x.t > a) })()")
            check(idle_after_audio, "character went idle only after audio playback started (follows the audio, not the run)")
            await shot("12-hermes-answer")
            check(not console, "no console errors")
    finally:
        proc.terminate()

asyncio.run(main())
print("\nRESULT:", "FAIL" if fails else "PASS", f"({len(fails)} failures)")
sys.exit(1 if fails else 0)
