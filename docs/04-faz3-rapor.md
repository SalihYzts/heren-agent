# Faz 3 Raporu — Control Dashboard (2026-09-10)

Durum: **tamamlandı.** Core 71 test · UI 17 vitest · **22 adımlık canlı tarayıcı e2e** (headless Chromium, gerçek core + gerçek Go agent) geçti, konsol hatası 0.

## Ne yapıldı

**Core eklemeleri** (`apps/core`): CORS (yalnız config'deki origin), yerleşik UI'ı `/` altından SPA fallback'le servis (`NERO_UI_DIR`), `GET /api/actions`, `/ws/events` bağlanınca `ui.snapshot` (cihazlar + bekleyen onaylar) → UI yeniden bağlanınca boş ekran yok. `device.online`/`device.paired` artık `name/platform/capabilities` taşıyor; yeniden bağlanan agent'ın yetenek listesi DB'de tazeleniyor.

**UI** (`apps/ui`, Vite + React 19 + TS, 234 KB JS):
| Parça | İş |
|---|---|
| `lib/store.ts` | Saf reducer: snapshot, online/offline, metrik, onay ekle/kaldır, etkinlik (200 kayıt, yeniden bağlanmada veri korunur) — 9 test |
| `lib/api.ts` | Bearer istemcisi + `/ws/events` üstel backoff'lu yeniden bağlanma |
| `Approvals` | Kim → hangi cihaz → ne, risk etiketi, parametreler, TTL geri sayımı, Onayla/Reddet — 4 test |
| `DeviceCard` | Canlı LOAD/RAM çubukları, yalnız cihazın bildirdiği action'lar, HIGH kırmızı, offline'da kapalı, boot girdileri → "NEXT BOOT" tuşları — 5 test |
| `Login` / `PairingModal` / `Activity` / `Audit` | API key girişi (sessionStorage), 6 haneli tek kullanımlık kod + komut satırı, canlı etkinlik, denetim kaydı (risk, onaylayan, süre, hata) |

Tasarım: #0a0a0a zemin, 1 px hairline paneller, kare köşe, mono metrik, kırmızı vurgu yalnız HIGH/onay/hata için; gradyan ve gölge yok.

## Canlı e2e (`apps/core/scripts/ui_e2e.py`, ekran görüntüleri `/tmp/nero-shots/`)

```
yanlış anahtar → "geçersiz anahtar"        doğru anahtar → dashboard, "core bağlı"
"+ Cihaz eşle" → 6 haneli kod → gerçek Go agent bu kodla başlatıldı
→ kart YENİLEMEDEN belirdi (online) → 10 s içinde gerçek /proc metrikleri çubuklarda
get status → toast + etkinlik satırı completed
get boot entries → NEXT BOOT: Windows Boot Manager / Limine* / debian / HP_TOOLS / …
shutdown → "onay bekliyor", onay kartı; audit sayısı DEĞİŞMEDİ (hiçbir şey çalışmadı) → Reddet → denied
hermes API'den set_next_boot(ZZZZ) → kart canlı belirdi → Onayla → agent'a ulaştı, agent bilinmeyen girdiyi reddetti (failed)
Denetim sekmesi → "by ui:dashboard" görünür
agent kapatıldı → kart offline, tuşlar disabled
```

## Kendim sürerken bulduğum hatalar

1. **Cihaz kartında hiç buton yoktu** (görsel doğrulama ile yakalandı): `device.paired/online` olayları `capabilities` taşımıyordu, UI olaydan kurduğu cihazda boş liste görüyordu. Core olaylarına eklendi (test), reducer güncellendi (2 test).
2. Sağ panelde yatay taşma + kesik action adları → 3 sütunlu grid, `overflow-x: hidden`, sütun 460 px.
3. e2e scriptinde `querySelector` geçersiz seçicide fırlatıyordu (test aracı hatası).

## Teknik borç

1. API key tarayıcıda (sessionStorage) — Faz 9'da kısa ömürlü UI oturumu/PIN.
2. `launch_app`/`restart_service`/`run_approved_command` parametreli action'lar için kartta form yok (yalnız API'den) — Faz 8 macro editörüyle birlikte.
3. Onay TTL'i geri sayımı istemci saatiyle; sunucuyla kayma olabilir (kozmetik).
4. Metrik geçmişi yok (yalnız son değer); grafik Faz 8.
5. Vite `erasableSyntaxOnly` yüzünden parametre-özellik sözdizimi yok — kozmetik.

## Sonraki: Faz 4 — Character Engine

Activity/Mood/Attention/Energy katmanları, zaman kuralları (`sleep_start`, `deep_sleep_start`), enerji modeli, event → animasyon girdileri; saat simülasyonuyla test. UI'da karakter alanı Faz 7'de; Faz 4 core'da `/api/state` + `character.*` olayları.
