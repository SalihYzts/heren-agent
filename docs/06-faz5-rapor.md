# Faz 5 Raporu — Hermes Bridge + MCP (2026-09-10)

Durum: **tamamlandı.** Core 115 pytest (+16) · UI 39 vitest (+3) · Go yeşil · **gerçek Hermes gateway (v0.21.0) ile iki canlı e2e** geçti (API + tarayıcı).

Ayrıca bu turda uygulama adı **Nero → Heren Agent** oldu (`heren_core`, `heren-agent`, `HEREN_*`, marka; commit `f602fa7`).

## Mimari (Hermes'e sıfır yama)

```
UI /api/ask ──▶ HermesBridge ──POST /v1/runs {input, session_id, instructions}──▶ hermes gateway :8643
                    ▲            ◀── SSE /v1/runs/{id}/events ─────────────────────┘      │
                    │  bus: hermes.thinking / tool.started / tool.completed|failed /       │ MCP (streamable HTTP)
                    │       speaking / text{sentence} / approval.request / error /         ▼
                    │       unavailable / done                                     core /mcp  (Bearer mcp_key)
                    └── CharacterHost dinler → thinking/working/speaking                 device_list
                        UI dinler → konuşma paneli, durum                                 device_status
                                                                                          device_action ──▶ ActionService.submit(requested_by="hermes")
```

**Bridge** (`hermes_bridge.py`): istek başına `instructions` ile karakter bağlamı (saat, mood, enerji) + kurallar ("cihazlar için yalnız device_* araçları; terminal/ssh yok; HIGH onay ister, tekrar deneme"). Cümle bölücü (`sentences()`: Türkçe, kısaltma ve `10.30` korumalı) → `hermes.text` cümle cümle (TTS için hazır). Oturum başına tek run (kilit). Hermes kapalıysa `hermes.unavailable` + `hermes.done`, `/api/ask` 500 dönmez.

**MCP** (`mcp_server.py`, `mcp` 2.2 `MCPServer`): 3 araç; hepsi ActionService'ten geçer → izin motoru aynen uygulanır. `/mcp` ayrı Bearer (`mcp_key`), `mcp_allowed_hosts` ile DNS-rebinding koruması opsiyonel. Hermes tarafı: `config.yaml` → `mcp_servers.heren.url` + `headers.Authorization: Bearer ${MCP_HEREN_TOKEN}` (Hermes'in kendi formatı).

**UI**: konuşma paneli (soru/cevap/hata satırları, "düşünüyor…/çalışıyor: terminal/hazır/erişilemez"), store'da `hermes` + `conversation`.

## Canlı kanıt — gerçek Hermes (`scripts/hermes_e2e.py`, `scripts/ui_hermes_e2e.py`)

```
"dev-local durumunu device_status ile kontrol et"
  events: hermes.thinking → hermes.tool.started(mcp__heren__device_status) → device.action.started/completed(get_status)
          → hermes.speaking → hermes.text → hermes.done          (17.5 s)
  answer: "dev-local (PussInBoots) çevrimiçi; Linux çalıştırıyor ve çalışma süresi 21.181 saniye."
  audit: get_status requested_by=hermes                          ✓

"dev-local'ı shutdown et"
  → /api/approvals: shutdown requested_by=hermes awaiting_approval ✓   çalışMADI ✓
  character attention=notification ✓
  answer: "Kapatma işlemi Heren panelindeki onayınızı bekliyor; istek kimliği: req_…"
  → deny → makine açık ✓

Tarayıcı: karakter [thinking, working, thinking, speaking, idle] sırasıyla geçti (MutationObserver),
          cevap "Anlık sistem yükü 1,10; … RAM %74" panelde, konsol hatası 0.
```
Ekran: `docs/shots/12-hermes-answer.png`.

## Canlı testte yakalanan hatalar

1. **`/mcp` 405** — `app.mount("/mcp")` yalnız `/mcp/…` eşliyor, MCP istemcisi tam `/mcp`'ye POST atıyor → SPA catch-all yakalıyordu. Birim testte görünmedi (httpx mount'a `/mcp/` ile gitmişti). Çözüm: yol kapsamlı ASGI shim; `/mcp` için 401 testi eklendi.
2. **mcp 2.x API** — `FastMCP` yok, `MCPServer`; `streamable_http_client(http_client=httpx2…)`; `is_error`. Test ona göre.
3. **DNS-rebinding koruması** "Host: t" reddediyordu → `mcp_allowed_hosts` config (boş = kapalı; auth zaten Bearer).
4. **test_app.py asılması** — WS context manager `__exit__` çağrılmıyordu; `_close(ws)` yardımcısı.

## Teknik borç

1. Hermes'in kendi `approval.request`'i (tehlikeli terminal komutu) UI'da yalnız event olarak var; onay/red butonu Faz 8'de (`respond_approval` hazır).
2. `hermes.text` cümleleri UI'da birleşiyor; TTS kuyruğu Faz 6.
3. Ayrı `HERMES_HOME` ile ikinci gateway çalıştırdım (`/tmp/heren-hermes`, port 8643); kalıcı kurulum için `deploy/` altına örnek `config.yaml`/`.env` gerekli.
4. `instructions` İngilizce sabit metin; çok dilli şablon Faz 7.
5. Hermes yanıt süresi 8–18 s (gpt-5.6, 1 tool çağrısı); karakter "working" ile köprülüyor, ama UI'da ilerleme metni yok.

## Sonraki: Faz 6 — Voice (wake word, VAD, STT, TTS) — ya da önce Faz 7 Living UI (art/animasyon zenginleştirme). Kararı sana bırakıyorum.
