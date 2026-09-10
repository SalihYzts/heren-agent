# Revizyon 1 — Kapsam daraltma (2026-09-10)

Kullanıcı kararı: **donanım/telefon/postmarketOS proje dışı.** Hedef: herhangi bir Linux sunucuda çalışan bağımsız uygulama. Önce tek makine, dağıtık kısım sonra.

## Faz 0 raporundan ne düşüyor, ne kalıyor

| Bölüm (00-faz0-mimari.md) | Durum |
|---|---|
| §1 satır 2-3 (Hermes nerede / pmOS ses) | **Düştü** — cevap: hepsi aynı Linux makinede |
| §4 UI framework — ARM/kiosk/telefon sütunları | **Düştü**; karar aynen React+Rive, kabuk = tarayıcı sekmesi (Tauri opsiyonel, sonra) |
| §8 Ses — "mic UI cihazında, işleme core'da" | **Sadeleşti**: mic ve hoparlör tarayıcıdan (WebAudio), işleme core'da — aynı makine, aynı yapı; dağıtık geçişte değişmez |
| §11 Redmi Note 10 Pro | **Tamamen düştü** |
| §13 risk 1 ve 10 (pmOS ses, ARM kiosk) | **Düştü** → liste 8'e indi |
| §9 stack, §5 agent protokolü, §7 güvenlik, §6 karakter motoru | **Aynen geçerli** |
| Roadmap Faz 1-9 | **Aynen geçerli**; Faz 9'daki "ARM ölçümü" → "kaynak ölçümü" |

## Tek makine geliştirme topolojisi

```
Linux makine (tek host)
├─ hermes gateway        :8642   (API_SERVER_ENABLED=true)
├─ nero-core             :8700   (FastAPI: bus, engine, bridge, Action API, MCP, agent hub, SQLite)
├─ nero-voice            (ayrı süreç, MVP+1)
├─ nero-ui               :5173 dev / core'dan statik servis
└─ device-agent (Go)     aynı makineye "localhost" cihazı olarak bağlanır  ← ilk gerçek cihaz
```

Agent'ın **dışa bağlanan WS** tasarımı korunuyor; tek makinede `ws://127.0.0.1:8700/agent`, dağıtıkta yalnız URL değişir. Pairing/imza/nonce Faz 2'de yine yapılır — tek makinede "gerekmez" diye atlanırsa dağıtıkta sonradan eklenmesi tüm protokolü kırar (kural 3: güvenlik sonradan eklenen özellik değil).

Dağıtığa geçiş listesi (ileride, tek satır değişiklik olmalı): `core.public_url`, TLS/Tailscale, agent kayıt URL'i. Mimaride başka değişiklik yok.

## Hâlâ açık kararlar (varsayılanla ilerlerim, itiraz yoksa)

| Karar | Varsayılan |
|---|---|
| Dil | Karakter ve UI **Türkçe**, kod/şema/log İngilizce |
| Onay | Yalnız dokunma/tıklama; sesli onay yok |
| Agent dili | Go |
| Uykulu üslup | MVP'de deterministik (prosodi + animasyon + şablon); LLM üslubu Faz 7'de opsiyonel |
| İlk gerçek cihaz | Geliştirme makinesinin kendisi (Linux); Windows agent Faz 2 ikinci yarısı |

## Faz 1 için sonraki adım (onay bekliyor)

`packages/protocol` şemaları (Device, Action, Event, Permission, Envelope) + core iskeleti + sahte agent + `POST /actions` LOW/HIGH akışı testi. Onay gelince başlarım; başlamadan önce dosya ağacını ve şema taslağını gösteririm.
