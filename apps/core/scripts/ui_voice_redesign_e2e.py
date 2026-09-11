#!/usr/bin/env python3
"""Real browser microphone pipeline with a generated WAV as Chromium's test mic.

No mocked STT/LLM/TTS responses. Requires running Heren + Hermes and local voice models.
The input device is synthetic, not the user's physical microphone.
Usage: python scripts/ui_voice_redesign_e2e.py BASE TEST_KEY [CDP_PORT]
"""
import asyncio
import base64
import io
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import wave

import numpy as np
from piper import PiperVoice
import websockets

ROOT = Path(__file__).resolve().parents[3]
BASE, KEY = sys.argv[1:3]
PORT = int(sys.argv[3]) if len(sys.argv) > 3 else 9336
# Heren runs behind its own self-signed cert for LAN phones; the harness trusts it explicitly.
INSECURE = ssl.create_default_context(); INSECURE.check_hostname = False; INSECURE.verify_mode = ssl.CERT_NONE
WS_SSL = INSECURE if BASE.startswith('https') else None
CHROME = Path.home() / '.cache/ms-playwright/chromium-1243/chrome-linux64/chrome'
OUT = Path('/tmp/heren-redesign-e2e')
OUT.mkdir(exist_ok=True)
checks = []


def check(ok, label):
    checks.append({'ok': bool(ok), 'label': label})
    print(('PASS ' if ok else 'FAIL ') + label, flush=True)
    if not ok:
        raise AssertionError(label)


def make_question(path):
    voice = PiperVoice.load(str(ROOT / 'data/voices/tr_TR-dfki-medium.onnx'))
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wav:
        voice.synthesize_wav('Merhaba Heren. Sen kimsin? Bir cümleyle anlat.', wav)
    with wave.open(io.BytesIO(buf.getvalue())) as wav:
        rate = wav.getframerate()
        x = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    samples = np.interp(np.arange(int(len(x) * 48000 / rate)) * rate / 48000, np.arange(len(x)), x)
    # Leading silence avoids device startup cutting the first word; the file is played once (%noloop),
    # after which the fake mic is silent → the app's silence detector must auto-send.
    audio = np.concatenate([np.zeros(24000), samples, np.zeros(4800)]).astype('<i2')
    with wave.open(str(path), 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(48000)
        wav.writeframes(audio.tobytes())
    return len(audio) / 48000


async def main():
    mic = OUT / 'question.wav'
    duration = make_question(mic)
    with tempfile.TemporaryDirectory(prefix='heren-browser-', ignore_cleanup_errors=True) as profile:  # chromium may still be flushing
        proc = subprocess.Popen([
            str(CHROME), '--headless=new', '--no-sandbox', '--disable-gpu',
            f'--remote-debugging-port={PORT}', f'--user-data-dir={profile}',
            '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
            f'--use-file-for-fake-audio-capture={mic}%noloop', '--ignore-certificate-errors',
            '--autoplay-policy=no-user-gesture-required', 'about:blank',
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            tabs = None
            for _ in range(50):
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json', timeout=1) as r:
                        tabs = json.load(r)
                    break
                except OSError:
                    await asyncio.sleep(.2)
            if tabs is None:
                raise RuntimeError('Chromium did not start')
            page = next(t for t in tabs if t['type'] == 'page')
            async with websockets.connect(page['webSocketDebuggerUrl'], max_size=2**26) as ws:
                serial = 0
                exceptions = []
                requests = []

                async def send(method, **params):
                    nonlocal serial
                    serial += 1
                    await ws.send(json.dumps({'id': serial, 'method': method, 'params': params}))
                    while True:
                        message = json.loads(await ws.recv())
                        if message.get('method') == 'Runtime.exceptionThrown':
                            d = message['params']['exceptionDetails']
                            exceptions.append((d.get('text') or '') + ' ' + str((d.get('exception') or {}).get('description', ''))[:300])
                        if message.get('method') == 'Network.requestWillBeSent':
                            requests.append(message['params']['request']['url'])
                        if message.get('id') == serial:
                            if 'error' in message:
                                raise RuntimeError(message['error'])
                            return message.get('result', {})

                async def js(expression):
                    result = await send('Runtime.evaluate', expression=expression, returnByValue=True, awaitPromise=True)
                    if 'exceptionDetails' in result:
                        raise RuntimeError(result['exceptionDetails'])
                    return result['result'].get('value')

                async def wait(expression, timeout=15):
                    deadline = time.monotonic() + timeout
                    while time.monotonic() < deadline:
                        if await js(expression):
                            return True
                        await asyncio.sleep(.2)
                    return False

                async def click(label):
                    check(await js(f"(() => {{ const b = [...document.querySelectorAll('button')].find(x => x.textContent.trim() === {json.dumps(label)}); if (!b || b.disabled) return false; b.click(); return true }})()"), 'click ' + label)

                async def shot(name):
                    r = await send('Page.captureScreenshot', format='png')
                    path = OUT / f'{name}.png'
                    path.write_bytes(base64.b64decode(r['data']))
                    print('SCREENSHOT ' + str(path), flush=True)

                await send('Runtime.enable')
                await send('Page.enable')
                await send('Network.enable')
                await send('Emulation.setDeviceMetricsOverride', width=1440, height=960, deviceScaleFactor=1, mobile=False)
                await send('Page.navigate', url=BASE)
                check(await wait("location.origin !== 'null' && document.readyState === 'complete'"), 'app loaded')
                check(await js("isSecureContext"), 'page is a secure context (mic allowed on phones): ' + BASE)
                await js(f"sessionStorage.setItem('heren.api_key', {json.dumps(KEY)})")
                await send('Page.addScriptToEvaluateOnNewDocument', source="""
                    window.__plays = []; window.__ended = 0; window.__micTracks = [];
                    // record how far each waveform swung (0..50 in the 300x100 viewBox) while it was active
                    window.__waveMax = { user: 0, heren: 0 };
                    setInterval(() => { for (const tone of ['user', 'heren']) {
                      const s = document.querySelector(`svg.wave[data-tone=${tone}]`); if (!s || s.dataset.active !== 'true') continue;
                      const d = s.querySelector('path')?.getAttribute('d') || '';
                      const ys = [...d.matchAll(/,([\\d.]+)/g)].map(m => +m[1]); if (!ys.length) continue;
                      const dev = Math.max(...ys.map(y => Math.abs(y - 50))); if (dev > window.__waveMax[tone]) window.__waveMax[tone] = dev; } }, 40);
                    window.__micBackend = null;
                    const AW = window.AudioWorkletNode; if (AW) { window.AudioWorkletNode = class extends AW { constructor(...a) { super(...a); window.__micBackend = 'worklet' } } }
                    const csp = AudioContext.prototype.createScriptProcessor; AudioContext.prototype.createScriptProcessor = function(...a) { window.__micBackend = 'script-processor'; return csp.apply(this, a) };
                    const play = HTMLMediaElement.prototype.play;
                    HTMLMediaElement.prototype.play = function() {
                      window.__plays.push(this.src); this.addEventListener('ended', () => window.__ended++, {once:true});
                      return play.call(this);
                    };
                    const get = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
                    navigator.mediaDevices.getUserMedia = async (...args) => {
                      const stream = await get(...args); window.__micTracks.push(...stream.getTracks()); return stream;
                    };
                """)
                await send('Page.navigate', url=BASE)
                check(await wait("!!document.querySelector('[data-testid=conversation]')"), 'conversation on the home screen')
                check(await wait("document.querySelector('[data-testid=character-panel]')?.dataset.pack === '/character/heren.json'"), 'real character art loaded')
                # two halves
                check(await js("!!document.querySelector('section[aria-label=Heren]') && !!document.querySelector('section[aria-label=Kumanda]')"), 'screen split: Heren half + control half')
                heren = json.loads(await js("JSON.stringify(document.querySelector('section[aria-label=Heren]').getBoundingClientRect())"))
                ctl = json.loads(await js("JSON.stringify(document.querySelector('section[aria-label=Kumanda]').getBoundingClientRect())"))
                check(heren['right'] <= ctl['left'] + 1 and heren['width'] > 300 and ctl['width'] > 300, f"halves side by side on tablet/desktop ({heren['width']:.0f}px | {ctl['width']:.0f}px)")
                # categories on the control half
                check(await js("!!document.querySelector('section[aria-label^=\"Sunucu\"]')"), 'category 1: server buttons')
                check(await js("!!document.querySelector('section[aria-label^=\"Diğer cihazlar\"]')"), 'category 2: other devices')
                check(await js("!!document.querySelector('section[aria-label=\"Senin düğmelerin\"]')"), 'category 3: user-assignable buttons')
                check(await wait("document.querySelectorAll('section[aria-label^=\"Sunucu\"] button.ctl').length >= 5"), 'server buttons rendered from the paired device')
                labels = await js("[...document.querySelectorAll('section[aria-label^=\"Sunucu\"] button.ctl')].map(b => b.getAttribute('aria-label'))")
                print('SERVER BUTTONS ' + json.dumps(labels, ensure_ascii=False), flush=True)
                check('Durumu göster' in labels and 'Yeniden başlat' in labels and 'Kapat' in labels, 'server essentials present (status/restart/shutdown…)')
                check(await js("!document.querySelector('.devices') && !document.querySelector('.log-row') && !document.body.innerText.includes('faster_whisper') || !!document.querySelector('.voice-details')"), 'no technical noise on the home screen')
                await shot('01-home-tablet')
                # nav: devices / logs / settings, then back
                await click('Cihazlar'); check(await wait("!!document.querySelector('.devices')"), 'devices view reachable')
                await click('Kayıtlar'); check(await wait("[...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Denetim')"), 'logs view reachable')
                await click('Ayarlar'); check(await wait("!!document.querySelector('section[aria-label=Ayarlar]')"), 'settings view reachable')
                check(await js("(() => { const r = [...document.querySelectorAll('input[name=theme]')]; return r.length >= 3 && !!document.querySelector('input[name=look]') })()"), 'settings: theme radios + character look')
                await js("[...document.querySelectorAll('input[name=theme]')].find(r => r.value === 'paper').click()")
                check(await wait("document.documentElement.dataset.theme === 'paper' && getComputedStyle(document.body).backgroundColor !== 'rgb(10, 10, 10)'"), 'theme switch repaints immediately')
                await shot('02-settings-paper')
                await js("[...document.querySelectorAll('input[name=theme]')].find(r => r.value === 'nothing').click()")
                # phone access + model choice + feature guide live in settings
                access = await js("JSON.stringify([...document.querySelectorAll('.access-urls a')].map(a => a.href))")
                print('ACCESS ' + str(access), flush=True)
                check(access and access != '[]' and 'https://' in access, 'settings show the LAN https address for phones')
                check(await wait("(() => { const i = document.querySelector('img.access-qr'); return !!i?.currentSrc && i.complete && i.naturalWidth > 0 })()"), 'settings render a QR for the phone address (image decodes)')
                await js("[...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Neler yapabilir?').click()")
                check(await wait("document.querySelectorAll('.guide-list dt').length >= 8"), 'feature guide lists what Heren can do')
                check(await wait("document.querySelector('select[aria-label=\"Sağlayıcı\"]') && document.querySelectorAll('select[aria-label=\"Sağlayıcı\"] option').length >= 2"), 'model picker lists providers from the Hermes install')
                providers = await js("[...document.querySelectorAll('select[aria-label=\"Sağlayıcı\"] option')].map(o => o.value)")
                print('PROVIDERS ' + json.dumps(providers), flush=True)
                def set_select(label, value):
                    return js(f"(() => {{ const i = document.querySelector('select[aria-label={json.dumps(label)}]'); const s = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set; s.call(i, {json.dumps(value)}); i.dispatchEvent(new Event('change', {{bubbles: true}})) }})()")
                await set_select('Sağlayıcı', 'copilot'); await asyncio.sleep(.2)
                models = await js("[...document.querySelectorAll('select[aria-label=Model] option')].map(o => o.value).filter(v => v && v !== '__custom')")
                print('MODELS copilot ' + json.dumps(models[:8]) + f' … ({len(models)})', flush=True)
                check(len(models) > 5, f'model list for copilot has real entries ({len(models)})')
                # pick the model the test gateway actually runs if listed, else the first one; the choice must travel
                chosen = 'gpt-4.1' if 'gpt-4.1' in models else models[0]
                await set_select('Model', chosen); await asyncio.sleep(.2)
                check(await js(f"JSON.parse(localStorage.getItem('heren.settings.v1') || '{{}}').model === {json.dumps(chosen)}"), f'model choice persisted in settings ({chosen})')
                if chosen != 'gpt-4.1':
                    # keep the live round-trip on the model this test gateway is known to serve
                    await set_select('Model', '__custom'); await asyncio.sleep(.2)
                    await js("(() => { const i = document.querySelector('input[aria-label=\"Model adı\"]'); const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; s.call(i, 'gpt-4.1'); i.dispatchEvent(new Event('input', {bubbles: true})) })()")
                    check(await js("JSON.parse(localStorage.getItem('heren.settings.v1') || '{}').model === 'gpt-4.1'"), 'free-text model entry works when the catalog lacks the model')
                    chosen = 'gpt-4.1'
                await click('Ana ekran')
                urllib.request.urlopen(urllib.request.Request(BASE + '/api/voice/stop', method='POST', headers={'Authorization': 'Bearer ' + KEY}), timeout=5, context=INSECURE).read()  # quiet leftovers from earlier runs
                # listen to the core bus in parallel: proves the browser really played (voice.playback.* come FROM the browser)
                bus = []
                async def listen():
                    async with websockets.connect(BASE.replace('http', 'ws') + '/ws/events?token=' + KEY, ssl=WS_SSL) as w:
                        async for m in w: bus.append(json.loads(m)['type'])
                bus_task = asyncio.create_task(listen()); await asyncio.sleep(.3)
                # tap Heren → mic opens, screen says it is listening
                check(await wait("[...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Konuşmaya başla' && !b.disabled)"), 'microphone available')
                await js("document.querySelector('[data-testid=character-stage]').click()")
                check(await wait("document.querySelector('[data-testid=character-caption]')?.textContent === 'Seni dinliyorum'"), 'tap on Heren → "Seni dinliyorum" on the character')
                check(await js("document.querySelector('[data-testid=voice-status]').dataset.listening === 'true' && !!document.querySelector('.listen-ring') && !!document.querySelector('meter')"), 'listening feedback: ring on stage + status + level meter')
                check(await wait("document.querySelector('[data-testid=ascii-frame]').dataset.anim === 'listening'"), 'character switches to the notice (listening) art')
                await asyncio.sleep(1.0)
                lvl = await js("+document.querySelector('meter').value")
                print(f'MIC LEVEL {lvl:.3f}', flush=True)
                check(lvl > 0.01, 'level meter reacts to real microphone input')
                check(await js("document.querySelector('svg.wave[data-tone=user]').dataset.active === 'true' && document.querySelector('svg.wave[data-tone=heren]').dataset.active === 'false'"), 'green user wave in front of Heren while listening (Heren wave off)')
                backend = await js('window.__micBackend')
                print('MIC BACKEND ' + str(backend), flush=True)
                check(backend == 'worklet', 'microphone captured through AudioWorklet (off the main thread)')
                await shot('03-listening')
                # NO second tap: the user stops talking and Heren sends by itself (speech → 1.5 s quiet)
                t0 = time.monotonic()
                check(await wait("document.querySelector('[data-testid=voice-status]')?.dataset.listening === 'false' && !document.querySelector('meter') && !document.querySelector('.listen-ring')", duration + 6), 'silence after speech auto-sends (no second tap; ring + meter gone)')
                print(f'AUTO-SEND after {time.monotonic() - t0:.1f}s (clip {duration:.1f}s)', flush=True)
                check(time.monotonic() - t0 < duration + 3.5, 'auto-send fired within ~1.5 s of the user going quiet')
                wave_user = await js('window.__waveMax.user')
                print(f'WAVE user max swing {wave_user:.1f}/50', flush=True)
                check(wave_user > 3, 'user wave actually moved with the voice')
                tracks = await js("JSON.stringify((window.__micTracks || []).map(t => t.readyState))")
                print('MIC tracks after send: ' + str(tracks), flush=True)
                if tracks != '[]':
                    check(await wait("window.__micTracks.every(t => t.readyState === 'ended')"), 'microphone tracks released after send')
                check(await wait("document.querySelector('[data-testid=voice-transcript]')?.textContent.toLocaleLowerCase('tr').includes('kimsin')", 180), 'real STT understood microphone input')
                sent = [u for u in requests if '/api/voice/transcribe' in u]
                print('TRANSCRIBE ' + json.dumps(sent), flush=True)
                check(sent and f'model={urllib.parse.quote(chosen)}' in sent[-1] and 'provider=copilot' in sent[-1], 'chosen model travels with the voice question')
                check(await wait("!!document.querySelector('.conv-row.heren .text')", 180), 'real Hermes response in conversation')
                print('ANSWER ' + str(await js("document.querySelector('.conv-row.heren .text').textContent")), flush=True)
                answer = await js("document.querySelector('.conv-row.heren .text').textContent")
                check('heren' in answer.lower() and len(answer) > 20, 'Hermes answered as Heren (knows who it is through the panel)')
                # The app reports playback to core only when <audio> really starts/ends (useVoice → api.playback).
                # That trail is the truth; the HTMLMediaElement.play hook is informational (may miss with fake audio).
                print('AUDIO play() hook calls: ' + str(await js('window.__plays.length')), flush=True)
                # Playback finished = the app's own signal (voice status leaves 'konuşuyor'), which fires on
                # <audio> ended/pause. window.__ended is informational: headless Chromium with a fake audio
                # device may never fire 'ended'.
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline and 'voice.playback.finished' not in bus: await asyncio.sleep(.2)
                print('BUS ' + json.dumps([t for t in bus if t.startswith('voice.')]), flush=True)
                check('voice.speech' in bus, 'core synthesized the answer (voice.speech on the bus)')
                check('voice.playback.started' in bus, 'browser reported playback started (its <audio> really played)')
                check('voice.playback.finished' in bus, 'browser reported playback finished')
                check(await wait("document.querySelector('[data-testid=voice-status]').dataset.speaking === '0'", 10), 'voice bar back to quiet after playback')
                wave_heren = await js('window.__waveMax.heren')
                print(f'WAVE heren max swing {wave_heren:.1f}/50', flush=True)
                check(wave_heren > 1, 'Heren wave behind the art moved while the answer played')
                check(await js("document.querySelector('svg.wave[data-tone=heren]').dataset.active === 'false'"), 'Heren wave off after playback')
                bus_task.cancel()
                print('AUDIO ended events: ' + str(await js('window.__ended')), flush=True)
                await shot('04-answer')
                await send('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=1, mobile=True)
                await asyncio.sleep(.5)
                check(await js('document.documentElement.scrollWidth <= innerWidth'), 'mobile has no horizontal page overflow')
                # halves must stack without painting over each other: control half starts where the Heren half ends
                geo = json.loads(await js("(() => { const a = document.querySelector('.half-heren').getBoundingClientRect(), b = document.querySelector('.half-control').getBoundingClientRect(), s = document.querySelector('.half-heren').scrollHeight; return JSON.stringify({aTop: a.top, aBottom: a.bottom, aScroll: s, bTop: b.top}) })()"))
                print('MOBILE geometry ' + json.dumps(geo), flush=True)
                check(geo['bTop'] >= geo['aBottom'] - 1 and geo['aBottom'] - geo['aTop'] >= geo['aScroll'] - 1, 'mobile: halves stacked, Heren half not clipped/overlapped by controls')
                await shot('04-mobile')
                print('EXC ' + json.dumps(exceptions, ensure_ascii=False), flush=True)
                check(not exceptions, 'no uncaught browser exceptions')
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait()


try:
    asyncio.run(main())
finally:
    (OUT / 'checks.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2))
print(f'RESULT: {len(checks)} checks passed')
