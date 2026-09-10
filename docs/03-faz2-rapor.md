# Faz 2 Raporu — Device Agent (Go) (2026-09-10)

Durum: **tamamlandı.** `make test`: core 67 test + Go 3 paket (`-race`) yeşil. Gerçek Go agent, gerçek core ile bu makinede canlı test edildi.

## Ne yapıldı

| Paket | Sorumluluk | Test |
|---|---|---|
| `internal/protocol` | Envelope, **Python ile bayt-uyumlu kanonik JSON** (sort_keys, ensure_ascii, `.0` float, reflect ile tüm slice/map/int tipleri), ed25519 imza/doğrulama | 6 + çapraz vektör (`packages/protocol/vectors/envelope_sign.json`, Python'dan üretildi; aynı seed → aynı imza) + Go imzasını Python core'un doğruladığı test |
| `internal/adapter` | `Adapter` arayüzü, `Runner` enjeksiyonu (root'suz test). **Linux**: /proc status+metrics, systemctl/loginctl, `restart_service`/`launch_app` isim allowlist regex'i, `run_approved_command` yalnız config allowlist, boot hedefi: systemd-boot `bootctl set-oneshot` → GRUB `grub-reboot` → **UEFI `efibootmgr -n`** (Limine/rEFInd/her firmware). **Windows**: `shutdown /s|/r`, LockWorkStation, `Restart-Service`, `bcdedit /enum firmware` parse + `bcdedit /set {fwbootmgr} bootsequence {GUID}` (tek seferlik BootNext, Linux bootloader'a dokunmaz) | 11 Linux + 2 EFI + 5 Windows |
| `internal/client` | Dışa bağlanan WS, hello/pairing (kod tek kullanımlık), welcome'dan core anahtarı pin, **core imzası olmayan/replay isteklerini çalıştırmaz**, heartbeat = `get_metrics`, üstel backoff yeniden bağlanma (kodsuz), anahtar uyuşmazlığında kalıcı ret → retry yok | 6 (sahte core httptest) |
| `cmd/nero-agent` | YAML config + flag'ler, anahtar dosyası (0600, ilk çalıştırmada üretilir), platforma göre adapter, SIGTERM | derleme |

Derleme: `make agent` → linux-amd64, linux-arm64, windows-amd64 (~7 MB statik, CGO yok). `deploy/nero-agent.service` hazır.

## Canlı kanıt (`scripts/e2e_go_agent.sh`, bu makine = dev-local)

```
get_status      → hostname PussInBoots, uptime 10957 s      (gerçek /proc)
get_metrics     → load1 0.88, ram 62% / 15201 MB            (gerçek /proc)
get_boot_entries→ backend=efi: Windows Boot Manager(0000), Limine(0001,default), debian(0004)…  (gerçek efibootmgr)
run_approved_command say-hi     → "hi from allowlist"
run_approved_command rm-everything → failed: not on the allowlist
restart_service "nginx; id"     → failed: invalid service name   (agent'a ulaşmadan reddedildi)
launch_app "sh -c id"           → failed: bare executable name
shutdown (hermes)               → awaiting_approval → DENY → denied   (makine kapanmadı)
```

## Canlı testte yakalanan ve düzeltilen hatalar

1. **Kanonik yazıcı `[]map[string]any`'yi tanımıyordu** → `get_boot_entries` sonucu gönderilemedi, core 10 s timeout'a düştü. Birim testte fakeRunner bunu hiç WS'e taşımadığı için görünmedi. Düzeltme: reflect tabanlı genel fallback + test; ayrıca agent artık encode hatasında core'a "failed" karesi yollar (timeout beklenmez).
2. **Bu makine ne systemd-boot ne GRUB** (Limine) → boot hedefi için üçüncü yol `efibootmgr` eklendi.

## Teknik borç

1. `set_next_boot` gerçek makinede **çalıştırılmadı** (BootNext'i değiştirmek istemedim); komut yolu birim testli. İlk gerçek deneme kullanıcı gözetiminde olmalı.
2. Windows adapter yalnız çapraz derlendi + birim test; gerçek Windows'ta koşmadı. `bcdedit` çıktı dili İngilizce varsayımı (`identifier`/`description`) — Türkçe Windows'ta etiketler farklı olabilir → test gerekli.
3. Agent root olarak koşuyor (systemd unit); `launch_app` root'ta GUI başlatamaz — kullanıcı oturumu için `systemd-run --user`/`loginctl` köprüsü Faz 8.
4. WoL (`wake`) adapter'da yok — komşu cihazdan gönderilmesi gerekir (core'un görevi), Faz 8.
5. Heartbeat her 10 s `get_metrics` koşturuyor (Windows'ta PowerShell çağrısı = ~200 ms CPU); interval config'e alınmalı.
6. `pkill -x` ile `stop_app` root'ta tüm kullanıcıların sürecini öldürür.

## Sonraki: Faz 3 — Control Dashboard (React)

Cihaz kartları (online/offline, metrikler canlı `/ws/events`), action butonları, onay sheet'i (HIGH), pairing kodu ekranı, audit listesi, boot hedefi seçici. Tasarım: sert/teknik, kare köşe, 1 px hairline, mono metrik.
