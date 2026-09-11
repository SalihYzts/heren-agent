// "Heren neler yapabilir?" — the in-app feature guide. One place, plain Turkish.
// Keep it honest: only things that exist and work; the last block says what does not.

export interface Feature { title: string; body: string }

export const FEATURES: Feature[] = [
  { title: 'Konuş', body: 'Heren’e dokun, konuş, tekrar dokun (ya da sus, kendisi gönderir). Söylediğin yazıya çevrilir, Hermes cevaplar, Heren sesli okur. Konuşurken kesmek için tekrar dokun.' },
  { title: 'Yaz', body: 'Alttaki kutuya yaz. “Sunucu nasıl?”, “PC’yi kilitle”, “Şu tuş neden çalışmadı?” — Heren hangi cihazların bağlı olduğunu ve az önce ne yaptığını bilir.' },
  { title: 'Sunucu düğmeleri', body: 'Kumanda yarısında 01 / SUNUCU: durum, kaynaklar, kilit, uyku, yeniden başlat, kapat, sonraki açılış. Düğmeler cihazın gerçekten yapabildiklerinden üretilir; yapamadığı şey görünmez.' },
  { title: 'Diğer cihazlar', body: '02 / DİĞER CİHAZLAR: sunucuya eşlediğin her Linux makine burada kendi düğmeleriyle listelenir. Eşleme: Cihazlar → Cihaz eşle → koddaki ajanı o makinede çalıştır.' },
  { title: 'Senin düğmelerin', body: '03: kendi kısayolların. Bir cihaz + bir işlem (+ gerekiyorsa servis/uygulama adı) seç, adını ver. Bu tarayıcıda saklanır; düzenlenebilir, silinebilir.' },
  { title: 'Onay', body: 'Tehlikeli işlemler (kapat, yeniden başlat, uyut, sonraki açılış) hemen çalışmaz: sağ üstte “Onaylar” sayacı artar, sen onaylarsın. Hermes kendi isteğini onaylayamaz.' },
  { title: 'Karakter', body: 'Heren dinlerken, düşünürken, iş yaparken ve konuşurken farklı görünür. Gece 23:00’ten sonra uyumaya başlar; uyandırırsan uykulu konuşur. Gece çok çalıştırırsan sabah da uykulu olur.' },
  { title: 'Telefondan / tabletten', body: 'Aynı Wi‑Fi’deysen Ayarlar → Telefondan eriş altındaki adresi aç (ya da QR’ı okut). Mikrofon için https şart; ilk girişte sertifikayı bir kez kabul et.' },
  { title: 'Model', body: 'Ayarlar → Model: Hermes’in bu makinede kimliği olan sağlayıcıları ve her birinin modellerini listeler; seç ya da “elle yaz”. Boş bırakırsan Hermes’in kendi varsayılanı kullanılır.' },
  { title: 'Tema ve görünüm', body: 'Ayarlar’dan tema (Nothing / Kağıt / Kor) ve Heren’in görünümünü seç. Yeni ASCII paketleri geldikçe listelenir.' },
  { title: 'Giriş', body: 'API anahtarı = HEREN_API_KEY. “Bu cihazda beni hatırla” işaretliyse 30 gün boyunca (her girişte uzar) sorulmaz; değilse sekme kapanınca unutulur. Çıkış yap ikisini de siler.' },
  { title: 'Henüz yok', body: 'Uyandırma kelimesi (“Heren!”) yok, dokunarak konuşuyorsun. Uzaktan (Wi‑Fi dışı) erişim için VPN/Tailscale kur; Heren kendisi internete açılmaz. Kapalı makineyi uyandırma (Wake-on-LAN) yok.' },
]
