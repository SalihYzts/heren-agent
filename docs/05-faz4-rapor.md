# Faz 4 Raporu — Character Engine (2026-09-10)

Durum: **tamamlandı.** Core 99 pytest (+28) · UI 36 vitest (+19) · Go 3 paket · **32 adımlık canlı tarayıcı e2e** (gerçek core + Go agent + headless Chromium) geçti, konsol hatası 0.

## Tasarım

**Motor** (`apps/core/nero_core/character.py`) — saf, deterministik, I/O yok, saat enjekte (`now: () -> datetime`).

| Katman | Değerler | Sürücü |
|---|---|---|
| Activity | idle · listening · thinking · speaking · working · sleeping · waking | assistant olayları (thinking/tool/speaking/done), dokunma/wake word, zaman (uyku/uyanış/timeout) |
| Mood | neutral · happy · sleepy · annoyed · confused | gece penceresi, enerji, uyku borcu; tepkiler (`reaction_duration_s`) |
| Attention | none · user · notification · device | bekleyen onay sayacı > tepki > kullanıcı etkileşimi |
| Energy | 0…1 | gece konuşma maliyeti, uykuda hızlı / gündüz idle'da yavaş toparlama |

Kurallar (hepsi `CharacterConfig`): gece = `[sleep_start, wake_time)`; gece idle `sleep_after_idle_s` (derin gecede `deep_sleep_after_idle_s`) → sleeping; sleeping → touch/wake word → waking(`waking_duration_s`) → listening(`listen_timeout_s`) → idle; `wake_time`'da kendiliğinden idle'a uyanır; gece etkileşimleri borç biriktirir, borç `debt_clear_time`'da silinir → sabah sleepy. `tick()` büyük zaman sıçramalarını `max_step_s` adımlarla entegre eder (enerji hesabı tick sıklığından bağımsız).

**Uyku yalnız sunum:** sleeping'de her metod çalışmaya devam eder; `device_action_completed` uyurken mood'u değiştirmez (test: `test_sleeping_is_presentation_only…`). Core, agent'lar, action pipeline'ı motoru hiç görmez.

**Host** (`character_host.py`) — bus ↔ motor köprüsü. Bus olayı → motor metodu tablosu (`character.touch`, `wakeword.detected`, `hermes.thinking/speaking/done`, `hermes.tool.started/completed/failed`, `device.action.completed`, `device.offline`, `ui.approval.needed/resolved`). Çıkış: yalnız değişince `character.state {schema, activity, mood, attention, energy}`. Kendi çıktısını yok sayar (geri besleme testi). Bus API'sine dokunulmadı.

**HTTP:** `GET /api/state` (devices + approvals + character), `POST /api/character/touch`; `ui.snapshot` artık `character` taşıyor.

**UI** (`apps/ui/src/character/`):
- `ascii.ts` — asset formatı (`{cell, fps, animations{"activity.mood"|"activity"|"default": {frames, fps?}}}`), çözümleme zinciri exact → activity → default → yerleşik `[ ? ]`; `normalizeFrames` her kareyi `cell`'e pad/clip eder, iç boşluklar korunur.
- `AsciiCharacterRenderer.tsx` — `<pre>` `white-space: pre`, mono, `width: Nch; height: Mlh` sabit; fps timer'ı; durum değişince frame 0; tek kareli animasyonda timer yok; `data-activity/mood/anim/fallback`.
- `defaultPack.ts` — 13×6 hücre, 7 activity + 5 mood varyantı, sade. Test: her activity için gerçek art var, hiçbir kare hücreyi aşmıyor, çok kareli animasyonlar gerçekten değişiyor. **Yeni art = bu dosyaya (veya ayrı JSON'a) anahtar eklemek; kod değişmez.**
- `CharacterPanel` — sağ sütun üstü; tıklama → `/api/character/touch`.

## Canlı kanıt (`scripts/ui_e2e.py`, Faz 4 adımları)

```
character panel renders · <pre>/white-space:pre/monospace
touch → listening (character.state ile canlı)   box [92.25,100.8] == [92.25,100.8]  (zıplamadı)
listening animasyonu kare değiştiriyor · fallback değil
listening 8 s sonra idle
shutdown onay beklerken ATTN notification · reddedince ATTN none
```
Ekran: `docs/shots/10-character-listening.png` — kutu, gözler, bacaklar hizalı; durum satırı "LISTENING · HAPPY" (az önce tamamlanan action'ın 3 s'lik happy tepkisi).

## Teknik borç

1. `hermes.*` olaylarını henüz kimse yaymıyor (Faz 5 bridge); motor yolu birim testli, canlıda yalnız touch/action/approval yolları görüldü.
2. Enerji/borç core restart'ında sıfırlanır (kalıcılık yok) — Faz 8/9'da settings tablosuna.
3. Mood öncelik sırası sabit (reaction > sleepy > neutral); "annoyed while sleepy" gibi bileşik ifadeler yok — asset zenginleşince bakılır.
4. Renderer `lh` birimi eski tarayıcılarda yok; fallback `line-height*rows` px gerekebilir.
5. `make test` hedefi bu ajan terminalinde asılıyor (araç sorunu); `pytest`/`go test`/`vitest` ayrı ayrı temiz.

## Sonraki: Faz 5 — Hermes Bridge
`/v1/runs` SSE istemcisi → `hermes.thinking/tool.*/speaking/done` olayları (motor hazır bekliyor), session yönetimi, `instructions` ile karakter bağlamı, MCP sunucusu (`device_action` → `ActionService.submit`, requested_by=hermes).
