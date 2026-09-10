# Faz 7 — ASCII karakter animasyonları

## Kapsam

Kullanıcının Karakter_Animation.zip paketindeki ASCII sanatı Living UI'ya bağlandı. Hermes, ses sağlayıcıları ve deterministik karakter motoru değiştirilmedi. Uyku yalnız sunumdur; core ve cihaz ajanları durmaz.

- `assets/character/heren/`: kaynak kareler, kaynak notları ve `pack.yaml`.
- 28 adlandırılmış kare, ortak 140×122 hücre, 11 animasyon tanımı.
- `apps/core/scripts/build_character_pack.py`: ortak boş kenarları hizalamayı koruyarak kaldırır; tüm kareleri aynı hücreye doldurur; bilinmeyen kare referansında başarısız olur. Üst dizindeki notları kare saymaz.
- `apps/ui/public/character/heren.json`: yeniden üretilebilir statik paket. Kaynaktan tekrar üretilen dosya `cmp` ile birebir doğrulandı.
- Paket v2: intro bir kez, loop tekrar; v1 inline kare desteği korunur. Eksik kareler atlanır; uygun animasyon yoksa fallback kullanılır.
- Runtime yükleme `/character/heren.json`; HTTP/ağ/şema hatasında yerleşik sanat ve hata bilgisi. Bozuk animasyon türleri, sayı olmayan/sonsuz FPS ve geçersiz hücre ölçüleri reddedilir.

## Durum eşlemeleri

| Durum | Sanat |
|---|---|
| idle | idle döngüsü; sleepy/happy varyantları |
| listening | notice intro → notice döngüsü |
| thinking | thinking intro → çene ovalama döngüsü |
| working | hızlı thinking döngüsü |
| speaking | done intro → idle döngüsü |
| waking | yavaş done dizisi → idle karesi |
| sleeping | sabit idle karesi, soluk sunum ve zzz |

Düşük enerji oynatma hızını yarıya indirir. Mood sınıfları renk sunumunu değiştirir. Konuşma animasyonu fonem/lip-sync değildir. Paket FPS ve özel mood dizileri uygulama tercihidir, sanatçının zamanlama belirtimi olarak sunulmaz.

## Bulunan ve giderilen görsel hata

İlk uygulamada küçük fontla `140ch` genişliği gerçek glif genişliğinden küçüktü; karakterin sağ tarafı kesiliyordu. Önceki e2e yalnız dış kutuyu ölçtüğü için bu hatayı yakalamıyordu.

Düzeltme: glifler 16px temel boyutta, gerçek içerik genişliğiyle ölçülür; transform ile sahneye sığdırılır ve ortalanır. E2e artık `scrollWidth/clientWidth` ve `scrollHeight/clientHeight` ile iç kırpılmayı da kontrol eder. Idle ve listening ekran görüntüleri görsel olarak incelendi: karakter bütün, ortalanmış, şapka/gözlük/yüz/kollar seçilebilir. ASCII yoğunluğu nedeniyle ince detaylar küçük panelde sınırlıdır.

## Doğrulama

- `make test`: **142 pytest geçti**; Go vet ve race testleri geçti.
- UI `vitest run`: **128 test geçti** (son paket doğrulama/fallback testleri dahil).
- UI `npm run build`: TypeScript ve üretim build'i başarılı.
- Gerçek paket: 7 activity × 5 mood render/çözümleme matrisi; fallback ve eksik kare yok.
- Canlı Chromium + core `:8701`: **14 kontrol geçti**, 0 başarısızlık; runtime paket, boyut, içerik kırpılmaması, idle kare değişimi, touch → listening, intro → loop, sabit sahne, idle'a dönüş, yakalanan JS exception olmaması.
- `git diff --check` temiz.
- Mevcut Starlette/AnyIO deprecation uyarısı devam ediyor (1 uyarı).

Canlı tarayıcı testi idle/listening akışını kapsar. Diğer durumlar gerçek paketle bileşen testinde doğrulandı; bu turda Hermes/ses uçtan uca senaryoları yeniden çalıştırılmadı. Wake-word detector eklenmedi; önceki bas-konuş yolu korunuyor.

## Yeniden üretme

Repo kökünden:

```sh
.venv/bin/python apps/core/scripts/build_character_pack.py assets/character/heren apps/ui/public/character/heren.json
cd apps/ui && npm run build
```

Statik JSON değişikliği kaynak derleme gerektirmez; üretim sunucusu `dist` servis ediyorsa yeni paketin oraya da dağıtılması gerekir.

## Kanıtlar

- [Idle](shots/13-art-idle.png)
- [Listening](shots/14-art-listening.png)
- Canlı e2e: `apps/core/scripts/ui_character_e2e.py <base-url> <test-api-key> <cdp-port>`.

Değişiklikler commit edilmeden bırakıldı.
