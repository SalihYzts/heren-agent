# Heren Agent

A living assistant for your home server. **Hermes Agent is the brain; Heren is the face and the hands.**

Heren runs on any Linux box and gives you a phone/tablet-first control panel with an ASCII character who
listens, thinks, talks — and gets sleepy at night. Behind it, a device agent executes commands on the
server and on every other machine you pair, with a permission model that keeps the dangerous stuff behind
a tap-to-approve gate.

> Status: early. Phases 1–7 are done and live-tested; the UI redesign (two-half home screen, voice,
> themes, per-request model choice) is in progress. Turkish UI; code and docs in English/Turkish mix.

## What it does

- **Talk to your server.** Tap Heren, speak, tap again — local STT (faster-whisper) → Hermes → local TTS
  (Piper). The character shows it is listening, thinking, working, speaking.
- **One-tap controls.** Status, metrics, lock, sleep, restart, shutdown, next-boot entry — generated from
  what each paired device actually declares. Add your own buttons for services and apps.
- **Other machines.** A small Go agent runs on each computer (Linux/Windows), connects *outbound* to the
  core, signs every message (ed25519 + nonce), and only runs what it declared it can run.
- **Safety by design.** LOW-risk actions run immediately, HIGH-risk ones wait for approval in the UI,
  CRITICAL ones are off by default. Hermes cannot approve its own requests. No SSH keys on the Hermes host.
- **A character, not a chatbot skin.** Deterministic state machine (activity / mood / attention / energy),
  sleep window at night, sleep debt if you keep it up late, ASCII animation packs you can swap.

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

Open `http://<server>:8700`, enter `HEREN_API_KEY`. Pair a device from **Cihazlar → Cihaz eşle**, run
the agent on that machine with the pairing code. Microphone needs HTTPS or `localhost`.

Voice config (`HEREN_CONFIG` yaml):

```yaml
tts_provider: piper
tts_options: { model: data/voices/tr_TR-dfki-medium.onnx }
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

See the phase reports in `docs/`. Open items: wake word (push-to-talk only for now), persistence of the
character's energy/sleep debt across restarts, Wake-on-LAN, real Windows validation, metric history.

## License

MIT — see `LICENSE`.
