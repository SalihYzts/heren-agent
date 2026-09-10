# Faz 1 Raporu — Core Protocol (2026-09-10)

Durum: **tamamlandı.** 67 test yeşil (`apps/core`, 0.4 s). Gerçek süreçlerle uçtan uca duman testi geçti.

## Ne yapıldı

| Modül | Sorumluluk | Test |
|---|---|---|
| `protocol.py` | Device / ActionRequest / ActionResult / Event / Envelope; risk sınıfları; bilinmeyen action → CRITICAL (fail-closed); `run_approved_command` serbest metin reddi | 9 |
| `security.py` | ed25519 imza/doğrulama, ReplayGuard (nonce + zaman penceresi, cihaz başına) | 9 |
| `bus.py` | in-proc async pub/sub, `device.*` ve `*` desenleri, hatalı handler diğerlerini bozmaz | 7 |
| `storage.py` | SQLite (WAL): devices, actions, audit, settings; audit'te secret alanları `[redacted]` | 8 |
| `actions.py` | **Permission engine**: LOW/MED otomatik, HIGH onay kuyruğu + TTL, CRITICAL kapalı, `hermes*` kendi isteğini onaylayamaz, offline → `DEVICE_OFFLINE`, her sonuç audit + event | 12 |
| `gateway.py` | Agent oturumları: 6 haneli tek kullanımlık pairing, anahtar eşleşmesi, imzasız/replay zarf reddi, heartbeat + reaper, imzalı `action.request` dispatch + timeout | 13 |
| `app.py` | FastAPI: `/api/devices`, `/api/actions`, `/api/approvals/*`, `/api/audit`, `WS /ws/agent`, `WS /ws/events` (UI olay akışı), Bearer auth | 9 |
| `config.py` | Tüm sabitler `Settings`'te; YAML + `NERO_*` env | — |
| `fake_agent.py` | Referans agent (Python): pair, imza, heartbeat, yeniden bağlanma; Go agent'ın uyum referansı | e2e |

## Uçtan uca kanıt (gerçek uvicorn + gerçek WS, `scripts/e2e_smoke.sh`)

```
LOW  get_status            → 200 completed  {"uptime_s":12}      audit: risk=low  approved_by=null
HIGH shutdown (hermes)     → 202 awaiting_approval
     hermes approve         → 403 "the agent cannot approve its own requests"
     ui:salih approve       → 200 completed (agent SIMULATED)     audit: risk=high approved_by=ui:salih
CRIT format_disk           → denied "critical actions are disabled"
agent öldürüldü            → device status=offline; get_status → device_offline (dispatch yok)
```

## Tasarım notları

- Agent **dışa bağlanır**; core tek port. Dağıtığa geçişte yalnız URL değişir.
- Onay kararı yalnız `ActionService` içinde; UI, MCP ve macro aynı `submit()`'ten geçer.
- UI olay akışı bus'ın birebir kopyası (`/ws/events`) → Faz 4 karakter motoru ve Faz 3 dashboard aynı akışı dinler.

## Teknik borç (açık)

1. **CORS/UI oturumu yok** — API key tarayıcıya gömülecek; Faz 3'te kısa ömürlü UI token'ı.
2. **Pairing kodu bellekte** — core yeniden başlarsa kod düşer (kabul edilebilir, 5 dk TTL).
3. **Onay TTL'i bellekte** — restart sonrası `created_at + ttl` fallback'i var, ama `expires_at` DB'ye yazılmalı.
4. **Tek onaylayıcı** — kim onaylayabilir listesi yok; `approved_by` serbest metin. Faz 9'da kimlik.
5. **`run_approved_command` allowlist** `Settings.approved_commands`'ta tanımlı ama agent'a henüz iletilmiyor (Faz 2).
6. **TLS yok** — tek makine varsayımı; dağıtıkta Tailscale veya pin.
7. Starlette TestClient httpx uyarısı (`httpx2`) — kozmetik.

## Sonraki: Faz 2 — Device Agent (Go)

Go kurulu değil (`which go` boş). Faz 2 başlangıcında `go` kurulacak (pacman). İlk hedef Linux adapter: `get_status`, `get_metrics`, `restart_service` (systemd), `launch_app`, `shutdown`/`restart` (systemctl), `set_next_boot` (`systemctl reboot --boot-loader-entry` / grub-reboot); ardından Windows adapter.
