#!/usr/bin/env python3
"""Live voice e2e: spoken WAV question → STT → Hermes → sentence clips (Piper) → served WAVs.
Usage: python scripts/voice_e2e.py http://127.0.0.1:8701 e2e-key
"""
import asyncio, io, json, sys, time, wave
import httpx, numpy as np, websockets
from piper import PiperVoice

BASE, KEY = sys.argv[1], sys.argv[2]
H = {"Authorization": f"Bearer {KEY}"}
fails = []
def check(c, m): print(("PASS " if c else "FAIL ") + m); (not c) and fails.append(m)

def speech_share(wav: bytes) -> float:
    with wave.open(io.BytesIO(wav)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float) / 32768
        fr = np.fft.rfftfreq(len(x), 1 / w.getframerate())
    p = np.abs(np.fft.rfft(x)) ** 2
    return float(p[(fr > 80) & (fr < 3000)].sum() / p.sum())

async def main():
    # 1. a *spoken* question, synthesized by a different voice path than the server uses for answers
    v = PiperVoice.load("../../data/voices/tr_TR-dfki-medium.onnx")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        v.synthesize_wav("dev-local bilgisayarımın durumunu device_status ile kontrol et ve tek cümleyle söyle", w)
    question_wav = buf.getvalue()

    events = []
    async def listen():
        async with websockets.connect(BASE.replace("http", "ws") + f"/ws/events?token={KEY}") as ws:
            async for m in ws:
                events.append(json.loads(m))
    task = asyncio.create_task(listen())
    await asyncio.sleep(0.5)

    async with httpx.AsyncClient(timeout=180) as c:
        st = (await c.get(BASE + "/api/state", headers=H)).json()
        print("   voice providers:", st["voice"])
        check(st["voice"]["tts"] == "piper" and st["voice"]["stt"] == "faster_whisper", "real providers loaded")

        t0 = time.time()
        r = await c.post(BASE + "/api/voice/transcribe", headers=H | {"Content-Type": "audio/wav"},
                         content=question_wav, params={"ask": "true"})
        print(f"   transcribe+ask {time.time()-t0:.1f}s →", json.dumps(r.json(), ensure_ascii=False)[:300])
        j = r.json()
        check(r.status_code == 200, "transcribe endpoint ok")
        low = j["text"].lower().replace("-", "").replace(" ", "")
        check("devlocal" in low and "durum" in low and "kontrol" in low, f"STT understood the question: {j['text']!r}")
        check(j["asked"] and j["ask"]["ok"], "hermes answered the transcribed question")
        answer = j["ask"]["text"]
        print("   answer:", answer)

        await asyncio.sleep(2.0)  # let the last clip synthesize
        types = [e["type"] for e in events]
        speech = [e["payload"] for e in events if e["type"] == "voice.speech"]
        texts = [e["payload"]["text"] for e in events if e["type"] == "hermes.text"]
        check("voice.transcript" in types, "voice.transcript on the bus")
        check(len(speech) == len(texts) and len(speech) >= 1, f"one clip per sentence ({len(speech)}/{len(texts)})")
        check([s["seq"] for s in speech] == list(range(len(speech))), "clips numbered in order")
        check([s["text"] for s in speech] == texts, "clip texts match the sentences")
        total = 0.0
        for s in speech:
            rr = await c.get(BASE + s["url"], headers=H)
            check(rr.status_code == 200 and rr.content.startswith(b"RIFF"), f"clip {s['seq']} served as WAV")
            share = speech_share(rr.content)
            check(share > 0.6, f"clip {s['seq']} is speech (80–3k share {share:.2f}, {s['duration_s']:.1f}s)")
            total += s["duration_s"]
        print(f"   total speech {total:.1f}s for {len(answer)} chars")
        check(total > 1.0, "answer audio is not trivially short")

        # 2. barge-in: stop must drop pending clips
        n = len(events)
        r = await c.post(BASE + "/api/voice/stop", headers=H)
        await asyncio.sleep(0.5)
        check(r.status_code == 200 and any(e["type"] == "voice.stopped" for e in events[n:]), "stop → voice.stopped")

    task.cancel()

asyncio.run(main())
print("\nRESULT:", "FAIL" if fails else "PASS", f"({len(fails)} failures)")
sys.exit(1 if fails else 0)
