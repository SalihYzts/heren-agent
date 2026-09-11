# Faz 8 — Yeniden tasarım, ses UX, telefon erişimi

## Kapsam

Kullanıcı istekleri (verbatim özet): ekran ikiye — Heren / kumanda; dokun-konuş; sessizlikte otomatik gönder;
dalga göstergesi (kullanıcı yeşil önde, Heren kendi renginde arkada); daha genç ses; dar ekranda çakışma yok;
Hermes modeli seçilebilsin; Hermes "şu tuş" deyince Heren'i anlasın; ayarlar (tema + görünüm);
aynı Wi‑Fi'daki telefon/tabletten erişim; tüm özellikleri anlatan bir yer.

## Yapılanlar

### Ekran
- İki yarı: sol Heren (sahne + dokun-konuş + sohbet), sağ kumanda. ≤900px'de üst üste blok.
- Kumanda 3 kategori: **01 Sunucu** (capability'den üretilen düğmeler, HIGH işaretli),
  **02 Diğer cihazlar** (eşlenmiş her makine kendi düğmeleriyle), **03 Senin düğmelerin** (localStorage).
- Nav: Ana ekran / Cihazlar / Kayıtlar / Ayarlar; sağ üstte onay sayacı.
- Dar ekran: 320–1024px DOM çakışma sondası (`/tmp/overlap_probe.py`) → **0 örtüşme, 0 yatay taşma**.
  Tek "clipped" bulgusu composer `<input>` (tarayıcı doğal kaydırması; kusur değil).

### Ses
- Dokun → dinle; **`SilenceDetector`** (`voice/silence.ts`): konuşma ≥300 ms sonra 1.5 s sessizlik → gönder;
  15 s hiç konuşma yok → sessizce bırak + uyarı. Saf fonksiyon, zaman enjekte, 4 test.
- Dalga: `components/Waveform.tsx` (saf SVG). Kullanıcı dalgası `--ok` yeşil, sahnede **önde** (z 2);
  Heren dalgası tema ön rengi, ASCII'nin **arkasında** (z 0). Heren seviyesi `audioPlayer` içinde
  `AnalyserNode` ile gerçek `<audio>` çıkışından alınır (`speechQueue.ts`).
- Daha genç ses: `voice/dsp.py` **WSOLA + yeniden örnekleme** pitch shift (tempo korunur);
  `PiperTTS(pitch_semitones=…)`. Ölçüm: dfki-medium f0 ≈ 111 Hz → +4 yarım ton ≈ 140 Hz,
  süre değişimi < %1, 80–3 kHz enerji payı korunuyor. `deploy/voice.example.yaml` +4.
- Mood prosody'si pitch'e eklenir (uykuluda düşer), taban `pitch_semitones` üzerine biner.

### Hermes
- `/api/ask` ve `/api/voice/transcribe?ask=true` `model`/`provider` alır → `/v1/runs` gövdesine geçer.
  Ayarlar → Model (boş = gateway varsayılanı). e2e: `?model=gpt-4.1&provider=copilot` isteğe binmiş.
- Her soruya `instructions` içinde kimlik + cihaz listesi + son denetim kayıtları
  ("'the button', 'this app' … they mean Heren").

### Telefon / tablet erişimi
- `HEREN_HOST=0.0.0.0 HEREN_TLS=true HEREN_TLS_DIR=…` → `netaccess.py` kendi imzalı sertifika üretir
  (SAN: hostname, `<host>.local`, tüm LAN IPv4; 3 yıl), uvicorn'a verir, adresleri loglar.
- `/api/state.access = {urls, tls, host}`; `/api/access/qr.svg` (segno, yalnız kendi adresleri).
- Ayarlar → **Telefondan eriş**: adres listesi + QR + sertifika notu; loopback'e bağlıysa nasıl açılacağı.
- Gerçek doğrulama: `https://192.168.1.150:8701` LAN IP'sinden 200; `isSecureContext === true`.

### Özellik rehberi
- `lib/features.ts` → Ayarlar → **Neler yapabilir?** (11 madde, sonuncusu "Henüz yok"). README güncellendi.

## Bulunan ve giderilen hatalar
- `HEREN_CONFIG` var olmayan bir dosyayı gösterince Heren **sessizce** `tts=none stt=none` ile açılıyordu
  (e2e'de "microphone available" FAIL ile yakalandı). Artık açıkça verilen yol yoksa boot'ta
  `FileNotFoundError` (test: `test_explicit_config_path_that_does_not_exist_is_an_error`).
- QR `svg_inline()` `xmlns` içermiyordu → blob URL'den `<img>` çizmiyordu (görselde boş alan). Tam SVG
  belgesi üretildi; core testi `xmlns` ister, e2e `naturalWidth > 0` ile çözümlenmeyi doğrular.
- `audioPlayer` level tap testi: rAF'ı microtask ile taklit edince `ended` hiç gelmiyordu (95 s askı) →
  macrotask (`setTimeout`) ile taklit.

## Testler
- Core pytest: **157** (netaccess 4, QR 1, model/provider 2, pitch/dsp 3, config 1 yeni).
- UI vitest: **163** (silence 4, waveform 3, level tap 1, settings/model/access/guide 3, waves-on-character 1).
- `tsc -b` temiz, `npm run build` ✓, `make test` (Go dahil) ✓.
- Canlı e2e `ui_voice_redesign_e2e.py` **https://127.0.0.1:8701** üzerinden, gerçek Piper (+4) /
  faster-whisper / Hermes (Copilot gpt-4.1): **48/48, rc=0**.
  - Sessizlikte otomatik gönder: klip 4.1 s (konuşma 0.55–3.60 s), gönderim dokunuştan 4.4 s sonra,
    ikinci dokunuş yok.
  - Kullanıcı dalgası sapması 50/50, Heren dalgası 49.6/50 (gerçek `<audio>` çıkışından).
  - `POST /api/voice/transcribe?ask=true&model=gpt-4.1&provider=copilot` — seçim isteğe bindi.
  - Cevap: "Ben Heren; ev sunucunu ve bağlı cihazlarını bu panel üzerinden kolayca yönetmeni sağlayan asistanım."
  - Tarayıcıda yakalanmamış istisna: 0. Ekranlar: `/tmp/heren-redesign-e2e/0{1..4}-*.png`.

## Faz 8b — eksik kapatma turu (aynı gün, kullanıcı test ederken)

Kullanıcı: "sunucuyu aç ben test edeyim sen de o sıra eksikleri tamamla". Sunucu `data/e2e/` altında kalıcı
(db, tls, Hermes test profili — hepsi `.gitignore`'da) açıldı; bu sırada kapatılanlar:

- **Model listesi.** Hermes `/v1/models` yalnız `hermes-agent` takma adını döndürüyor — seçici için işe
  yaramaz. Gerçek kaynak: Hermes kurulumunun `auth.json → credential_pool` (hangi sağlayıcıların kimliği
  var) × `agent.models_dev.list_provider_models` (models.dev kataloğu). `models_catalog.py` bunu Hermes'in
  **kendi venv'inde alt süreçle** okur (içe aktarma yok), 1 saat önbellek. `/api/models` → Ayarlar'da
  sağlayıcı/model `<select>`; "Listede yok, elle yaz…" ve katalog gelmezse düz `<input>` yedeği.
  Canlı: 3 sağlayıcı, 90 model, 0.98 s.
- **Oturum.** Giriş ekranında "Bu cihazda beni hatırla (30 gün)": işaretliyse anahtar localStorage'da
  kayan süreyle; değilse sekmeyle ölür. Çıkış ikisini de siler (`lib/session.ts`, 4 test).
- **Karakter kalıcılığı.** `CharacterEngine.export_state/restore_state` (enerji, borç, uyuyor mu, son
  etkileşim/tick; şema 1). `CharacterHost` her değişimde `settings` tablosuna yazar, açılışta okur; ilk
  `tick()` kapalı kalınan süreyi motor çalışıyormuş gibi bütünler (uyku toparlaması, sabah uyanma, borç
  silme). Gelecekten gelen damgalar ve saat geri gitmesi yok sayılır. Core restart testi: enerji 0.42 →
  yeniden açılışta 0.42.
- **AudioWorklet.** `voice/micCapture.ts`: worklet blob modülü (`heren-mic`, 4096'lık parçalar) → yoksa /
  CSP engellerse `ScriptProcessorNode`. `useVoice` yalnız `Capture` arayüzünü görür; level/dalga/sessizlik
  davranışı aynı. e2e tarayıcıda hangi yolun kullanıldığını doğrular.

Testler: core **170**, UI **172**, Go (yeni: `TestPinnedCAFileTrustsSelfSignedCore`), build.

- **Go ajan `--ca-file`.** TLS açıkken ajanın kendi imzalı sertifikaya güvenme yolu yoktu → hiç
  eşlenemezdi. Sertifika **iğneleme** eklendi (`RootCAs` = yalnız o PEM; `InsecureSkipVerify` yok, eksik
  dosya = kalıcı hata). Bu makine `wss://127.0.0.1:8701` üzerinden gerçekten eşlendi (`dev-pc`, 12 yetenek).

Canlı e2e (`https://127.0.0.1:8701`, gerçek Piper +4 / whisper / Hermes Copilot gpt-4.1, gerçek eşlenmiş
cihaz): **52/52, rc=0**. Mikrofon yolu `worklet`; katalog 28 copilot modeli; elle yazma yedeği; otomatik
gönder 4.3 s (klip 4.2 s); dalgalar 50/50 ve 48.8/50; yakalanmamış istisna 0.

## Kalanlar
- Uyandırma kelimesi yok. Wake-on-LAN yok. Gerçek Windows doğrulaması yok. Metrik geçmişi yok.
- Gerçek telefon donanımıyla kullanıcı testi (sertifika kabul akışı tarayıcıya göre değişir).
- Tek komutla kurulum betiği.
