# Heren Agent

A living assistant for your home server. **Hermes Agent is the brain; Heren is the face and the hands.**

Heren runs on any Linux box and gives you a phone/tablet-first control panel with an ASCII character who
listens, thinks, talks — and gets sleepy at night. Behind it, a device agent executes commands on the
server and on every other machine you pair, with a permission model that keeps the dangerous stuff behind
a tap-to-approve gate.

> Status: early but usable. Phases 1–8 are done and live-tested (see `docs/`). Turkish UI; code and docs
> in English/Turkish mix. The in-app feature guide lives under **Ayarlar → Neler yapabilir?**

## What it does

- **Talk to your server.** Tap Heren and speak; when you go quiet for 1.5 s it sends by itself (or tap
  again). Local STT (faster-whisper) → Hermes → local TTS (Piper). A green waveform in front of the
  character shows it hears you; the character's own waveform behind the art moves while Heren talks.
- **From your phone or tablet.** Same Wi‑Fi, open the address shown under **Ayarlar → Telefondan eriş**
  (or scan the QR). Heren mints a self-signed certificate so the browser allows the microphone.
- **One-tap controls.** Status, metrics, lock, sleep, restart, shutdown, next-boot entry — generated from
  what each paired device actually declares. Three groups: 01 the server, 02 other paired machines,
  03 your own buttons (service restarts, app launches — stored in the browser).
- **Other machines.** A small Go agent runs on each computer (Linux/Windows), connects *outbound* to the
  core, signs every message (ed25519 + nonce), and only runs what it declared it can run.
- **Safety by design.** LOW-risk actions run immediately, HIGH-risk ones wait for approval in the UI,
  CRITICAL ones are off by default. Hermes cannot approve its own requests. No SSH keys on the Hermes host.
- **Hermes knows it is Heren.** Every question carries the paired devices and the last actions as
  context, so "the button didn't work" means something. Pick the Hermes model/provider per panel in
  **Ayarlar → Model**.
- **A character, not a chatbot skin.** Deterministic state machine (activity / mood / attention / energy),
  sleep window at night, sleep debt if you keep it up late, ASCII animation packs you can swap.
- **Themes.** Nothing (dark, default), Paper (light), Ember (dark + red). More character looks as packs arrive.

## Architecture

```
phone / tablet browser ──▶ heren-core (FastAPI, :8700) ──▶ Hermes gateway (/v1/runs SSE)
        ▲  ws events              │  ▲                              │
        │                         │  └── /mcp  ◀── device tools ────┘
        │                         ▼
        └────────────── device agents (Go, outbound WS, signed envelopes)
```

- `apps/core` — Python 3.12 core: event bus, character engine, Hermes bridge, MCP server, action/permission
  service, voice host, SQLite storage.
- `apps/ui` — React + TypeScript + Vite. ASCII character renderer, voice bar, control panel, settings.
- `agents/device-agent` — Go device agent (Linux + Windows adapters).
- `packages/protocol` — shared protocol vectors.
- `assets/character` — ASCII frames + `pack.yaml` (built into `apps/ui/public/character/heren.json`).
- `docs/` — one report per phase, with screenshots and the live e2e evidence.

## Run it

```sh
make setup                      # venv (uv), core deps, go modules
cd apps/ui && npm install && npm run build && cd ../..
scripts/fetch_voices.sh         # Turkish Piper voice (~63 MB) → data/voices/

# Hermes: enable the API server and point it at Heren's MCP (see deploy/hermes-config.snippet.yaml)
HEREN_API_KEY=change-me HEREN_MCP_KEY=change-me-too \
HEREN_HERMES_ENDPOINT=http://127.0.0.1:8642 HEREN_HERMES_API_KEY=<hermes-api-key> \
HEREN_UI_DIR=$PWD/apps/ui/dist HEREN_CONFIG=deploy/voice.example.yaml \
.venv/bin/python -m heren_core
```

Open `http://localhost:8700`, enter `HEREN_API_KEY`. Pair a device from **Cihazlar → Cihaz eşle**, run
the agent on that machine with the pairing code.

### Phone / tablet on the same Wi‑Fi

Browsers only allow the microphone on `localhost` or HTTPS, so for phones Heren must listen on the LAN
with TLS:

```sh
HEREN_HOST=0.0.0.0 HEREN_TLS=true HEREN_TLS_DIR=data/tls ... .venv/bin/python -m heren_core
```

On first start Heren writes a self-signed certificate (SAN = hostname + every LAN IP) into
`HEREN_TLS_DIR` and logs the addresses; the same list (plus a QR) appears in **Ayarlar → Telefondan
eriş**. Accept the certificate once on the phone. Heren never opens itself to the internet — for
remote use put it behind Tailscale/WireGuard.

Device agents then connect over `wss://` and pin that certificate (no "skip verify" mode exists):

```sh
heren-agent -core wss://<server>:8700/ws/agent -ca-file /path/to/data/tls/cert.pem -pair <code>
```

The panel's login has **"Bu cihazda beni hatırla (30 gün)"**; unchecked, the key dies with the tab.

Voice config (`HEREN_CONFIG` yaml):

```yaml
tts_provider: piper
tts_options: { model: data/voices/tr_TR-dfki-medium.onnx, pitch_semitones: 4 }   # +4 = younger voice
stt_provider: faster_whisper
stt_options: { model: small, device: cpu, compute_type: int8 }
```

Both default to `none` (silent) when not configured — the app still works, just text-only.

## Test

```sh
make test                        # core pytest + go vet/test -race
cd apps/ui && npx vitest run     # UI
```

Live end-to-end scripts (need a running core + Hermes + a Chromium): `apps/core/scripts/*_e2e.py`.

## Roadmap / known gaps

See the phase reports in `docs/`. Open items: wake word (tap-to-talk only for now), Wake-on-LAN, real
Windows validation, metric history, a one-command installer.

## License

MIT — see `LICENSE`.
