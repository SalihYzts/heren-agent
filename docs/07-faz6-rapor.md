# Faz 6 Raporu — Voice (2026-09-10)

Durum: **tamamlandı.** Core 138 pytest (+23) · UI 55 vitest (+16) · Go yeşil · **gerçek Piper + faster-whisper + gerçek Hermes** ile iki canlı e2e geçti (API, tarayıcı).

## Ne var

```
mikrofon (bas-konuş) ─PCM→WAV 16k─▶ POST /api/voice/transcribe?ask=true ─▶ STT ─▶ HermesBridge
                                                                              │
hermes.text {cümle} ─▶ VoiceHost kuyruğu ─prosodi(mood,enerji)─▶ TTS ─▶ voice.speech {seq,url}
                                                                              │
UI SpeechQueue: seq sıralı, blob <audio> ─▶ POST /api/voice/playback started|finished ─▶ karakter SPEAKING
```

- **Sağlayıcılar** (`voice/providers.py`): `TTSProvider.synthesize(text, prosody) → AudioClip`, `STTProvider.transcribe(wav, lang) → Transcript`. Yerleşik: `none` (sessiz/boş, her zaman), `piper` (yerel TTS), `faster_whisper` (yerel STT). `register_tts/stt` ile eklenir; bilinmeyen ad ya da başlatma hatası → `none` + log, süreç çökmez (canlıda doğrulandı: model yolu eksikken `tts=none`).
- **Prosodi** `prosody_for(mood, energy)`: sleepy → 1.25–1.45× yavaş (enerjiyle), happy 0.95, düşük enerji 1.15. Yalnız hız; içerik değişmez.
- **VoiceHost**: `hermes.text` → sıralı sentez (thread'de) → `voice.speech {run_id, seq, clip_id, url, text, duration_s}`; `voice.interrupt` → kuyruğu at, **sentez ortasındaki cümleyi duyurma** (generation sayacı), `voice.stopped`; `voice.error` ölümcül değil; klipler bellekte sınırlı (`voice_max_clips`, eskisi düşer).
- **HTTP**: `GET /api/voice/audio/{id}.wav` (bearer), `POST /api/voice/transcribe?ask=` (RIFF şart, 400), `POST /api/voice/stop`, `POST /api/voice/playback {started|finished}`; `/api/state.voice {tts, stt, language}`.
- **Karakter**: `speech_started/finished` — Hermes run'ı bitse de ses bitene kadar SPEAKING kalır; ses yoksa `done` ile idle. Motor saf kaldı.
- **UI**: `SpeechQueue` (seq sıralı, eksik seq bekler, yeni run eskiyi geçer, hata atlar), `encodeWav` (Float32 → 16-bit mono, 48k→16k ortalama ile decimation), `useVoice` (ScriptProcessor kayıt, <0.3 s'yi yollamaz, konuşmaya basınca barge-in), `VoiceBar` (sessiz/konuşuyor +N/dinliyor, Durdur, ● Konuş bas-konuş, stt=none ise mikrofon yok).

Config (yaml; dict seçenekler env'den geçmez):
```yaml
tts_provider: piper
tts_options: { model: data/voices/tr_TR-dfki-medium.onnx }
stt_provider: faster_whisper
stt_options: { model: small, device: cpu, compute_type: int8 }
```
`scripts/fetch_voices.sh` sesi indirir (63 MB, `data/` gitignore'da).

## Ölçümler (bu makine, CPU)

| | |
|---|---|
| Piper TR sentez | 4.0 s ses → **0.14 s** (22.05 kHz) |
| Prosodi 1.35× | 3.99 s → 5.18 s (uygulandığı kanıtlı) |
| Ses kalitesi | 80–3000 Hz enerji payı **0.89–0.95**, flatness 0.47 (gürültü değil, konuşma) |
| faster-whisper small int8 | ilk yükleme 116 s (indirme), sonrası **~1 s** / 4 s ses |
| STT roundtrip | "Merhaba ben Heren. Sunucu 3 gündür açık yük düşük." — birebir |
| Canlı: konuşulan soru → STT → Hermes (MCP aracı) → cevap | **11–15 s** uçtan uca |

## Canlı kanıt

`scripts/voice_e2e.py`: Piper ile *söylenmiş* soru WAV'ı → `/transcribe?ask=true` → STT `"Devlocal bilgisayarımın durumunu device status ile kontrol et ve tek cümleyle söyle."` → Hermes `device_status` çağırdı → cevap `"dev-local (PussInBoots) çevrimiçi; …"` → 1 cümle = 1 klip, seq 0, WAV servis edildi, konuşma bandı 0.89, 6.5 s → `stop` → `voice.stopped`. **PASS 14/14.**

`scripts/ui_hermes_e2e.py` (headless Chromium, gerçek Hermes): karakter `thinking → working → thinking → speaking → idle`; `<audio>.play()` 1 klip; ses çubuğu `konuşuyor → sessiz`; karakter idle'a **ses başladıktan sonra** geçti; konsol hatası 0. **PASS 19/19.** Ekran: `docs/shots/12-hermes-answer.png`.

## Yakalananlar

- Interrupt testi ilk halinde zayıftı: kod sabote edilince yine geçti → "sentez ortasındaki cümle duyurulmamalı, kuyruktakiler sentezlenmemeli" diye sıkılaştırıldı; sabotaj artık kırmızı, 3× stabil.
- `piper` `PiperTTS(model=...)` zorunlu; env ile geçilemez → yaml `tts_options`. Hata yolu `none`'a düşürüyor.
- STT "dev-local"ı "Devlocal" yazıyor; e2e karşılaştırması tire/boşluk bağımsız.
- Araç, `Bearer ${key}` şablonunu `***` diye maskeleyerek yazdı (api.ts) → build kırıldı; Python ile onarıldı.

## Teknik borç

1. Wake word yok (VAD/`openWakeWord` Faz 7+); bas-konuş var.
2. `ScriptProcessorNode` deprecated (AudioWorklet'e taşınmalı); mikrofon yalnız https/localhost.
3. Uykulu üslup yalnız hız; ses tonu/pitch yok (Piper `noise_scale` bağlı, kullanılmıyor).
4. Whisper modeli ilk açılışta ~2 dk indirir; `deploy/` için önceden indirme adımı yok.
5. Klip belleği süreç içi; çoklu core örneği yok (kapsam dışı).

## Sonraki: Faz 7 — Living UI (ASCII art zenginleştirme, uykulu/yorgun sunum, cümle-senkron dudak/animasyon, wake word).
