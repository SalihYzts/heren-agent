# Faz 0 — Araştırma ve Mimari Raporu

Tarih: 2026-09-10 · Durum: **onay bekliyor, kod yazılmadı**
> **Revizyon 1 (aynı gün):** telefon/pmOS/ARM kapsam dışı; hedef tek Linux makine, dağıtık sonra. §1 satır 2-3, §11 ve §13 madde 1/10 geçersiz. Bkz. `01-revizyon-kapsam.md`.
Kaynaklar: hermes-agent.nousresearch.com/docs (bugünkü), yerel kurulum `~/.hermes/hermes-agent` (v0.21.0, `gateway/platforms/api_server.py` ve `tui_gateway/` doğrudan okundu), postmarketOS wiki (xiaomi-sweet, 9 Eyl 2026), k2-fsa sherpa-onnx, openWakeWord.

---

## 1. Prompt analizi — eksik ve çelişkili noktalar

| # | Konu | Sorun | Karar gerekiyor mu |
|---|------|-------|--------------------|
| 1 | **Dil** | Prompt hiçbir yerde dil söylemiyor. Türkçe olacaksa STT/TTS/wake-word seçimleri tamamen değişir (Türkçe TTS sesi az, Türkçe wake-word modeli yok). | **Evet** |
| 2 | **Hermes nerede koşuyor?** | "Kendi home sunucumuz" deniyor ama ilk hedef cihaz Redmi Note 10 Pro. Telefon sunucu mu, sadece ekran mı? 6 GB RAM'li telefonda Hermes + STT + TTS + UI birlikte koşmaz. | **Evet** |
| 3 | **pmOS'ta ses BOZUK** | postmarketOS wiki (xiaomi-sweet): `Audio: Broken`, `Proximity: Broken`, `Fingerprint: Broken`. ARM64 Linux'ta telefon mikrofonu/hoparlörü yok → ses katmanı bu cihazda çalışmaz. Bluetooth çalışıyor (BT kulaklık/hoparlör olası ama güvenilmez). | **Evet** — §11'de seçenekler |
| 4 | **Kişilik katmanı ikilemi** | "Hermes'in sonucu ile sunum ayrı" + "cevabı uykulu anlatsın". Uykulu anlatım metni değiştirmeyi gerektirir; metni kim değiştirir? İkinci LLM çağrısı (maliyet, gecikme, halüsinasyon riski) vs. prosodi+animasyon+şablon (deterministik). | Öneri §6 |
| 5 | **İki onay sistemi** | Hermes'in kendi tehlikeli-komut onayı var; bizim Action API'de de HIGH/CRITICAL onayı var. Hermes `terminal` aracıyla `ssh pc sudo poweroff` yazarsa bizim izin modelini **tamamen atlar**. | Öneri §7 — Hermes'e cihaz kontrolü için yalnız bizim aracımız verilmeli |
| 6 | **Onay UI'ı** | Sesle gelen HIGH komutta onay nerede alınacak? Tablet dokunma mı, sesli "evet" mi (sesli onay replay/yanlış tanıma riski)? Zaman aşımı ne? | Öneri §7 |
| 7 | **Uyku ne engeller?** | "Uyurken servisler durmamalı" — doğru. Uyku yalnızca sunum katmanı; hiçbir işlevi engellememeli. Enerji modeli formülü yok. | Öneri §6 |
| 8 | **Kaç kullanıcı?** | Tek hane varsayımı; kullanıcı kimliği/sesle kimlik yok. HIGH onayını kim verebilir? | Varsayım: tek yetkili, sonradan genişler |
| 9 | **KDE Connect** | Sohbette geçti, promptta yok. Mevcut PC'lerde zaten kurulu; "komut çalıştır" yapabiliyor. Ama daemon+D-Bus oturumu ister, Windows'ta zayıf, onay/audit yok. | Adapter olarak eklenir, ana yol değil |
| 10 | **Hermes sürümü** | Yerel kurulum 6428 commit geride. `/v1/runs` yerelde var (doğrulandı) ama docs'taki `subagent.*` olayları, `Idempotency-Key` gibi şeyler eski sürümde eksik olabilir. | Faz 5 öncesi `hermes update` |

---

## 2. Hermes entegrasyonu (resmi docs + yerel kaynak doğrulandı)

Hermes üç programatik yüzey sunuyor (`developer-guide/programmatic-integration`):

| Yüzey | Taşıma | Bize uygunluk |
|-------|--------|---------------|
| ACP | JSON-RPC/stdio | IDE'ler için; bize gereksiz |
| TUI gateway | JSON-RPC stdio/WS | Onay, clarify, wake.* olayları var ama **iç protokol**, sürümle değişir, tek süreçle bağlı |
| **API server** | HTTP + SSE | `hermes gateway` ile ayrı süreç, kararlı, dile bağımsız → **seçim** |

### Seçilen yol: `POST /v1/runs` + `GET /v1/runs/{id}/events` (SSE)

Yerel `api_server.py` ile doğrulanan uçlar: `/v1/runs`, `/v1/runs/{id}`, `/v1/runs/{id}/events`, `/v1/runs/{id}/approval`, `/v1/runs/{id}/steer`, `/v1/runs/{id}/stop`, `/health`, `/v1/capabilities`.
Olaylar (yerel `api_server_runs.py`): `message.delta`, `tool.started`, `tool.completed`, `approval.request`, `approval.responded`, `run.completed`, `run.cancelled`, `run.steered`.

Bu olaylar bizim event bus'a birebir eşlenir:
```
tool.started     → hermes.tool.started  → Activity=working
message.delta    → assistant.speaking    → metin akışı + TTS cümle cümle
approval.request → ui.approval.needed    → karakter "izin istiyor" pozu
run.completed    → assistant.idle
```
`session_id` verilerek sohbet sürekliliği korunur; `instructions` alanıyla karakter bağlamı (saat, mood, enerji) **istek başına, geçici** enjekte edilir — Hermes'in kalıcı SOUL.md/config'ine dokunulmaz.

Kurulum: `~/.hermes/.env` → `API_SERVER_ENABLED=true`, `API_SERVER_KEY=…`; `hermes gateway` → `127.0.0.1:8642`.

### Hermes'in cihazlara komut vermesi: MCP sunucusu (Hermes'e sıfır yama)

Device Gateway kendi Action API'sini **MCP (streamable HTTP)** olarak da yayınlar; Hermes `hermes mcp add nero --url http://gateway:8700/mcp` ile bağlanır (yerel `hermes_cli/mcp_config.py` `--url` destekliyor). Araçlar:
`device_list`, `device_status`, `device_action(device_id, action, params)`, `macro_run(name)`.

Neden plugin değil MCP: plugin `~/.hermes/plugins/` içinde Python'dur ve Hermes'in iç API'sine bağlanır; MCP ise standarttır, Hermes değişse/yerine başka ajan gelse de aynı sunucu çalışır ("Hermes değişse bile cihaz ağı yaşasın"). Plugin yalnız gerekirse ikinci seçenek (`ctx.register_approval_transport` ile onayları bizim UI'a yönlendirmek için ileride işe yarayabilir).

**Kritik güvenlik kuralı (§1/5):** API server'a giden isteklerde Hermes'in `terminal`/`ssh` ile cihazlara doğrudan ulaşması engellenmeli. Yöntem: Hermes'in koştuğu makine cihaz ağına SSH anahtarı taşımaz; cihaz kontrol yolu yalnız MCP aracıdır; Hermes'e `instructions` ile "cihaz işlemlerinde yalnız device_action kullan" denir. Toolset kısıtı (`/v1/capabilities` → toolsets) Faz 5'te ölçülür.

---

## 3. Mimari (nihai)

```
┌────────────────────── UI Device (telefon/tablet/PC) ──────────────────────┐
│  Living Character UI (web, kiosk)                                          │
│   ├─ Character Renderer (Rive state machine)   ├─ Dashboard               │
│   ├─ Mic capture (WebAudio → PCM/WS)           ├─ Approval sheet          │
│   └─ Audio playback                            └─ Settings                │
└──────────────────────────────┬─────────────────────────────────────────────┘
                               │ WSS (event bus + audio frames)  /  HTTPS (REST)
┌──────────────────────────────┴───────────── Core Server (x86 / Pi / mini PC) ─┐
│  nero-core (Python, FastAPI, tek süreç, modüler)                              │
│   ├─ Event Bus (in-proc pub/sub → WS fan-out)                                 │
│   ├─ Character Engine (Activity/Mood/Attention/Energy, zaman kuralları)       │
│   ├─ Hermes Bridge (/v1/runs SSE istemcisi, session yönetimi, instructions)   │
│   ├─ Action API (REST) + MCP server (aynı handler'lar)                        │
│   ├─ Permission Engine (LOW/MED/HIGH/CRIT, onay kuyruğu, audit)               │
│   ├─ Device Gateway (agent WS hub, heartbeat, registry)                       │
│   └─ Storage (SQLite: devices, actions, approvals, audit, settings, macros)   │
│  nero-voice (ayrı süreç): Wake → VAD → STT → [text] ; TTS ← [text+prosody]   │
└───────────────┬──────────────────────────────┬────────────────────────────────┘
                │ outbound WSS (agent bağlanır) │ HTTP :8642
      ┌─────────┴──────────┐            ┌───────┴───────┐
      │ Device Agent (Go)  │            │ Hermes gateway│──MCP──▶ nero-core
      │ Linux / Windows    │            │ (+ LLM)       │
      └────────────────────┘            └───────────────┘
```

Bağımlılık yönü: UI → core; agent → core; Hermes → core (MCP); core → Hermes (/v1/runs). **UI hiçbir zaman agent'ı, agent hiçbir zaman Hermes'i görmez.**

---

## 4. UI framework karşılaştırması

| Seçenek | Karakter animasyonu | ARM64 telefon | Dashboard | Not |
|---------|--------------------|---------------|-----------|-----|
| **Web UI (React/Solid) + kiosk** | Rive/Canvas/WebGL, GPU'lu | Android kiosk: mükemmel; pmOS: Cog/WPE hafif | Doğal | Tek kod tabanı, her cihazda aynı; ses/mikrofon tarayıcı API'siyle |
| Tauri v2 (raipy tecrübesi) | Aynı web | Linux ARM'da WebKitGTK ağır; Android build mümkün | Doğal | Masaüstünde iyi; telefonda kiosk tarayıcıdan avantajı yok |
| Flutter | Rive native, iyi | Linux-embedded ARM çalışır, 60-100 MB | İyi | Yeni dil (Dart), ekibin bilgisi yok |
| Godot 4 | En iyi (skeletal, shader) | ARM Linux export var | Zayıf (form/tablo UI çile) | Karakteri Godot'ta yapıp dashboard'u web'de yapmak = iki uygulama |
| Qt/QML (Kirigami) | QML animasyon orta | Plasma Mobile native | İyi | pmOS'ta en doğal ama ses zaten yok; Windows ajanına etkisi yok |

**Öneri:** Web UI (TypeScript, React — ekip biliyor; Solid ikinci seçenek). Masaüstünde Tauri kabuğu opsiyonel; telefonda kiosk tarayıcı. Karakter: **Rive** (durum makinesi dosya içinde, `Activity`/`Mood`/`Energy` girdilerini doğrudan besleriz; runtime ~100 KB; WASM+Canvas GPU). Renderer soyutlanır (`CharacterRenderer` arayüzü) — Lottie/Canvas'a geçiş Character Engine'i etkilemez.

Tasarım dili: sert/teknik yüzey, kare köşe, 1 px hairline, düz panel, mono metrik (kullanıcı tercihi) — karakter alanı bunun içinde tek "yumuşak" öğe olur, kontrast bilinçli.

---

## 5. Device Agent protokolü

| | REST | WebSocket | gRPC | MQTT |
|---|---|---|---|---|
| Realtime durum | ✗ (polling) | ✓ | ✓ stream | ✓ |
| NAT arkası agent (port açmadan) | ✗ | ✓ (outbound) | ✓ (outbound stream) | ✓ |
| Tarayıcı istemcisi | ✓ | ✓ | ✗ (grpc-web şart) | ✗ (WS köprüsü) |
| Windows servis binary boyutu | küçük | küçük | orta | küçük |
| Broker gerekir | ✗ | ✗ | ✗ | ✓ |
| Ekip yükü | düşük | düşük | yüksek | orta |

**Hibrit karar:**
- **Agent ↔ Core:** WebSocket, **agent dışa bağlanır** (core'un tek portu var; agent hiç port dinlemez → "korumasız public endpoint" sorunu kökten çözülür). Heartbeat 10 s, metrik 30 s (yapılandırılabilir).
- **UI/Hermes → Core:** REST (Action API) + MCP. UI olay akışı: WebSocket.
- **MQTT:** yok; ileride Home Assistant/ESP köprüsü istenirse adapter.
- gRPC: reddedildi (tarayıcı dostu değil, küçük ekip için fazla).

Mesaj zarfı (JSON, imzalı):
```
{ id, ts, nonce, device_id, type: "action.request", payload:{action, params, risk, request_id}, sig }
```

**Agent dili: Go.** Tek statik binary, Windows/Linux/ARM64 çapraz derleme tek komut, servis kurulumu (systemd / Windows Service) kütüphaneyle, WoL ve süreç yönetimi kolay. Rust ikinci seçenek; Python reddedildi (Windows'a runtime taşımak).

Adapter katmanı: `LinuxAdapter` (systemd, loginctl, grub-reboot / `systemctl reboot --boot-loader-entry` / `efibootmgr -n`), `WindowsAdapter` (`shutdown`, `sc`, `bcdedit /set {fwbootmgr} bootsequence {GUID}` — UEFI BootNext eşdeğeri, GRUB'a dokunmadan), `KdeConnectAdapter` (opsiyonel, `kdeconnect-cli`).

Dual boot güvenli akış: `get_boot_entries` (LOW) → `set_next_boot(entry)` (HIGH, onay) → `restart` (HIGH, aynı onay içinde) → agent yeniden bağlanınca `device.online{os:"linux"}` doğrulaması.

---

## 6. Character Engine ve kişilik katmanı

Dört bağımsız katman (promptla aynı): Activity, Mood, Attention, Energy.

**Enerji modeli (öneri, Faz 4'te kalibre edilir):**
```
gündüz idle:      E += 0.02/dk (E≤1)
sleep_start sonrası (23:00) uyuyorsa: E += 0.05/dk
gece uyandırılıp konuşturulursa:      E -= 0.03/etkileşim, "gece borcu" D += 1
sabah: Mood = sleepy iff D > threshold; D öğlene doğru sıfırlanır
Mood.sleepy = E < 0.35 || (saat ∈ [23,06))
```
Sabit yok: `sleep_start`, `deep_sleep_start`, `energy_*` hepsi config.

**Kişilik katmanı — iki aşama:**
- **MVP (deterministik, LLM yok):** Hermes metni değişmez. Uykuluk şu kanallarla verilir: TTS prosodi (Piper `length_scale` 1.25 → yavaş, hafif düşük pitch), konuşma öncesi kısa şablon ("hmm… tamam…") — şablon listesi Türkçe/İngilizce config'de —, Rive `Mood=sleepy`, gecikmeli göz kırpma. Teknik gerçek değişemez çünkü metne dokunulmuyor.
- **Faz 7+ (opsiyonel):** Hermes `/v1/runs` isteğine `instructions` ile "şu an 00:43, çok uykulusun; içerik ve doğruluk aynı kalsın, üslup değişsin" — tek LLM çağrısı, ek maliyet yok; ama teknik gerçekleri koruma testleri (sonuç=başarı ise metinde "hata" geçmemeli) zorunlu. İkinci LLM ile yeniden yazma **reddedildi** (gecikme + çift halüsinasyon).

Uyku hiçbir servisi durdurmaz; sadece `Activity=sleeping` ve wake-word/dokunma → `waking → listening`.

---

## 7. Güvenlik ve threat model (ilk)

| Tehdit | Etki | Önlem |
|--------|------|-------|
| Hermes prompt injection → HIGH action | PC kapanır, boot değişir | HIGH/CRIT **her zaman** insan onayı, onay UI'da (Hermes onaylayamaz); onay `request_id`'ye bağlı, 60 s TTL |
| Hermes izin modelini `terminal`/`ssh` ile atlar | Tüm model boşa | Hermes hostunda cihazlara SSH anahtarı yok; cihaz yolu yalnız MCP; Hermes API key'i yalnız core'da |
| Replay: kaydedilmiş `shutdown` mesajı | Tekrar kapatma | Her mesajda nonce+ts, agent son 5 dk nonce'larını tutar, ±30 s saat toleransı |
| Sahte agent kaydı | Yanlış cihaza komut | Pairing: UI'da 6 haneli kod → ed25519 anahtar çifti; agent kimliği = public key parmak izi; core `known_devices` |
| Sahte core (agent'ı kandırma) | Agent'a komut | Agent, core sertifikasını pinler (TLS pin veya WireGuard/Tailscale içinde plain) |
| Ağ dinleme | Token/komut sızar | LAN içinde bile TLS (self-signed, pin) **veya** WireGuard/Tailscale overlay; öneri: Tailscale önerilir, mTLS Faz 9 |
| UI cihazı çalınması/ele geçmesi | Tam kontrol | UI oturumu kısa ömürlü token; HIGH için UI'da PIN (Faz 9) |
| Sesli sahte onay (TV'den "evet") | HIGH action | MVP'de onay yalnız dokunmayla; sesli onay ileride + konuşmacı doğrulama |
| `run_approved_command` genişlemesi | Rastgele komut | Yalnız önceden config'de tanımlı, parametresiz komut kimlikleri; serbest metin yok |
| Log'a secret sızması | | Audit yalnız action id/params allowlist alanları; token/parola alanları şemada `redact` |
| Agent binary yükseltme | Supply chain | İmzalı release, agent kendini güncellemiyor (MVP), manuel |

Risk sınıfı → davranış: LOW otomatik · MEDIUM otomatik + audit · HIGH UI onayı · CRITICAL UI onayı + PIN (Faz 9'a kadar tamamen kapalı).

---

## 8. Ses mimarisi

```
Mic (UI cihazı, WebAudio 16 kHz PCM) ──WS──▶ nero-voice
  Wake: openWakeWord (Hermes de bunu kullanıyor; "Nero" için özel model eğitimi gerekir — openwakeword.com / livekit-wakeword sentetik veri)
        alternatif: sherpa-onnx KWS (açık sözlük, eğitim yok; ancak model yalnız EN/ZH fonemleri — "Nero" EN fonemle denenebilir)
  VAD:  Silero VAD (ONNX, ARM'da ~1 ms/frame)
  STT:  faster-whisper (core sunucuda GPU varsa `small/medium`, Türkçe iyi) — CPU'da sherpa-onnx whisper/zipformer
  ──▶ metin → Hermes Bridge
TTS:  Piper (Türkçe `tr_TR-dfki-medium` mevcut, ARM64'te gerçek zamanlıdan hızlı, length_scale ile prosodi) ; Kokoro (TR yok) ; bulut: OpenAI/ElevenLabs
  ──▶ cümle cümle stream → UI oynatır (Hermes `message.delta` cümle sınırında kesilir → düşük gecikme)
```
Arayüzler: `STTProvider.transcribe(pcm)`, `TTSProvider.synthesize(text, prosody)`, `WakeProvider.feed(pcm)->bool`. Provider seçimi config; vendor lock yok.
Kesme (barge-in): kullanıcı konuşmaya başlarsa oynatma durur, `run.stop` çağrılır.

Ses işleme **UI cihazında değil core'da** koşar (ARM telefon RAM'i korunur; Hermes'in "client capture" deseniyle aynı).

---

## 9. Teknoloji yığını (gerekçeli)

| Katman | Seçim | Gerekçe |
|--------|-------|---------|
| Core server | Python 3.11+, FastAPI, uvicorn, SQLite (aiosqlite), pydantic | Ses kütüphaneleri Python-first; Hermes ekosistemiyle aynı dil; tek süreç kolay |
| MCP server | `mcp` Python SDK (streamable HTTP) aynı süreçte mount | Action API ile aynı handler'lar |
| Voice | ayrı Python süreci; openwakeword, silero-vad, faster-whisper, piper-tts | Çökerse core etkilenmez |
| Device Agent | Go 1.22+, gorilla/nhooyr websocket, kardianos/service | Tek binary, çapraz derleme |
| UI | TypeScript, React, Vite, Rive runtime, Zustand; Tauri v2 kabuk opsiyonel | Ekip bilgisi; kiosk tarayıcıda çalışır |
| Protokol tanımı | JSON Schema (`packages/protocol`) → TS tipleri + Pydantic + Go struct üretimi | Tek doğruluk kaynağı |
| Ağ | Tailscale/WireGuard önerisi + TLS pin | §7 |
| Test | pytest, go test, vitest, Playwright (kiosk UI); protokol için schema uyumluluk testi | |

---

## 10. Repo yapısı (monorepo — evet)

```
nero/
├── apps/
│   ├── ui/                 # React + Rive (character + dashboard)
│   └── core/               # FastAPI: bus, engine, bridge, action api, mcp, gateway
├── services/
│   └── voice/              # wake/vad/stt/tts süreci
├── agents/
│   └── device-agent/       # Go; adapters/{linux,windows,kdeconnect}
├── packages/
│   ├── protocol/           # JSON Schema + codegen (ts/py/go)
│   └── character-engine/   # saf TS/py state machine? → karar: core'da Python, UI'a state stream
├── deploy/                 # systemd unit'leri, kiosk scriptleri, Tailscale notları
├── docs/
└── Makefile / justfile     # make dev, make agent-linux-arm64, make test
```
Promptun önerdiği `/services/hermes-bridge` ve `/services/device-gateway` ayrı süreç olarak **birleştirildi** (core içinde modül): iki-üç kişilik ekip için ayrı süreç = ayrı deploy = gereksiz karmaşıklık. Modül sınırları import kurallarıyla korunur, ileride bölünebilir.

---

## 11. Redmi Note 10 Pro kararı (kritik)

| Seçenek | Ses | UI | Hermes | Not |
|---------|-----|----|--------|-----|
| A. pmOS mainline | ✗ bozuk | ✓ (Cog/WPE veya Phosh+Firefox) | Telefonda değil | Şu an ses yok; BT ses denenebilir ama garanti yok |
| **B. Android/LineageOS + kiosk tarayıcı (PWA)** | ✓ mic+hoparlör tarayıcıdan | ✓ | Sunucuda | En düşük risk; telefon = ince istemci; Termux gerekmez |
| C. Android + Termux'ta Hermes | ✓ | ✓ | Telefonda (6 GB'de zayıf) | Hermes resmi Termux desteği var ama LLM bulutta olmak zorunda |

**Öneri: B.** Telefon yalnızca UI + mikrofon/hoparlör; Hermes, ses işleme ve core ayrı bir Linux makinede (mevcut RTX 4060'lı PC veya mini PC/Pi). pmOS ses çalışırsa A'ya geçiş UI için sıfır değişiklik (aynı web uygulaması).

---

## 12. Fazlı roadmap

| Faz | Kapsam | Çıkış kriteri |
|-----|--------|---------------|
| 0 | Bu doküman | Onay |
| 1 | `packages/protocol` şemaları; core iskeleti: bus, storage, Action API (REST), permission engine; sahte agent | Şema testleri; `POST /actions` LOW/HIGH akışı testi |
| 2 | Go agent: Linux (status, metrics, restart, shutdown, launch, service), pairing, imzalı zarf, WS reconnect; Windows aynı | Gerçek PC'de `restart_service` + replay testi |
| 3 | Dashboard UI: cihaz kartları, online/offline, metrik, action butonları, onay sheet, özel buton/macro | Playwright: onaysız HIGH action çalışmaz |
| 4 | Character Engine: 4 katman, zaman kuralları, enerji, event → Rive girişleri; basit Rive karakter | Saat simülasyonuyla state testleri |
| 5 | Hermes Bridge: `/v1/runs` SSE, session, instructions; MCP server; `hermes mcp add`; hata/offline davranışı | "Nero, PC'yi Linux'a geçir" → onay → boot değişir |
| 6 | Voice: wake ("Nero" modeli), VAD, STT, TTS stream, barge-in, provider soyutlaması | Uçtan uca sesli komut, gecikme ölçümü |
| 7 | Living UI: animasyon seti, göz takibi, uyku/uyanma, cihaz olaylarına tepki, uykulu prosodi | Görsel QA (kendim UI'dan sürerek) |
| 8 | Automation: macro, çoklu cihaz, zamanlama, Hermes'in önerdiği macro'lar onayla | `Start Development` macro'su |
| 9 | Hardening: mTLS/pin, PIN, audit raporu, stres, ARM ölçümü (RAM/CPU/idle güç), kurtarma | Güvenlik testleri geçmeden HIGH/CRIT prod'a açılmaz |

MVP = Faz 1-5 (metin + dokunma, ses yok). Ses MVP+1.

---

## 13. En riskli 10 teknik nokta

1. **pmOS'ta ses yok** — hedef cihaz mimariyi belirliyor (§11).
2. **Hermes'in izin modelini atlaması** (`terminal`/`ssh`) — mimariyle değil, deploy disipliniyle çözülür; test edilmeli.
3. **"Nero" wake-word'ü** — hazır model yok; eğitim kalitesi (yanlış tetikleme oranı) belirsiz, özellikle Türkçe ortamda.
4. **Türkçe TTS kalitesi** — Piper TR sesi var ama tek ses, duygu yok; "uykulu" yalnız hız/pitch ile.
5. **Uçtan uca ses gecikmesi** — wake→STT→Hermes(tool çağrıları)→TTS; Hermes tarafı 5-30 s sürebilir; karakter "düşünüyor/çalışıyor" ile köprülemeli.
6. **Hermes sürüm sürüklenmesi** — yerel kurulum 6428 commit geride; `/v1/runs` olay adları değişebilir; bridge'de sürüm kontrolü (`/v1/capabilities`).
7. **Windows dual-boot** — `bcdedit bootsequence` firmware'e göre tutarsız; her makinede doğrulama gerekir.
8. **Uyku modundaki PC'ye ulaşmak** — WoL BIOS/NIC ayarına bağlı; agent uykuda olayı bildiremez.
9. **Kişilik katmanının gerçeği bozması** — Faz 7'de LLM üslup enjeksiyonu açılırsa doğruluk testi şart.
10. **ARM telefonda kiosk tarayıcının uzun süreli kararlılığı** — bellek sızıntısı, ekran uykusu, WS kopmaları; watchdog/yeniden yükleme gerekli.

---

## 14. MVP kapsamı

**İçinde:** core (bus, storage, Action API, permission), 1 Linux + 1 Windows agent (status/metrics/restart/shutdown/launch/service/next-boot), dashboard, onay akışı, basit Rive karakter (idle/listening/thinking/working/speaking/sleeping + sleepy mood), Hermes bridge (metin), MCP `device_action`, zaman tabanlı uyku.
**Dışında:** ses (wake/STT/TTS), macro, CRITICAL sınıf, mTLS (Tailscale varsayımı), KDE Connect, çoklu kullanıcı.

---

## Onay için kararlar

1. Dil: Türkçe mi, İngilizce mi, ikisi de mi? (STT/TTS/wake seçimi buna bağlı)
2. Redmi Note 10 Pro: Android+kiosk (B) mi, pmOS (A) mı?
3. Core+Hermes hangi makinede koşacak? (RTX 4060 PC / ayrı mini PC / Pi)
4. Onay yalnız dokunmayla mı (öneri), sesli "evet" de olsun mu?
5. Agent dili Go kabul mü? (alternatif Rust)
6. Uykulu üslup MVP'de deterministik (prosodi+animasyon+şablon) — kabul mü?
