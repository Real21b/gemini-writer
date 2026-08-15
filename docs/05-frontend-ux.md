# 5. Frontend ve Kullanıcı Deneyimi

Bu ürünün rakiplerinden ayrışacağı yer model değil, **bekleme deneyimi**dir. Bir roman
üretimi 20-90 dakika sürer. Kullanıcının bu sürede ne gördüğü, ürünün kalitesi olarak
algılanır.

## 5.0 UX ilkeleri

1. **Boş ekran yok.** Her an: ne yapılıyor, ne kadar ilerlendi, ne kadar kaldı, ne kadara
   mal oldu.
2. **Süreç okunabilir olsun.** Ham log değil; insan diline çevrilmiş adımlar
   ("3. bölüm yazılıyor — 3.100 kelime"). Ham detay isteyen için "geliştirici görünümü".
3. **Metin kahramandır.** Arayüzün merkezinde kullanıcının romanı olmalı, ajanın logu değil.
4. **Kullanıcı her an müdahale edebilir.** Duraklat, yönlendir, reddet, düzenle.
5. **Kesinti ölümcül olmasın.** Sekmeyi kapatmak koşuyu durdurmaz; geri dönünce kaldığı
   yerden izlenir.
6. **Okumaya saygı.** Uzun metin okunacak; tipografi, satır uzunluğu (65-75 karakter),
   satır aralığı ve karanlık mod birinci sınıf konular.

---

## 5.1 Bilgi mimarisi

```
/                     → Projeler (giriş ekranı)
/new                  → Yeni yazım sihirbazı
/p/[projectId]        → Proje: Okuyucu (varsayılan sekme)
/p/[projectId]/run/[runId]  → Canlı koşu görünümü
/p/[projectId]/bible  → Hikâye kutsal kitabı (karakterler, mekânlar, zaman çizgisi)
/p/[projectId]/history→ Sürümler ve değişiklikler
/settings             → API anahtarı, bütçe, varsayılan model, tema
```

---

## 5.2 Ekran: Yeni yazım sihirbazı (`/new`)

Tek ekran, üç bölüm — çok adımlı sihirbaz yapmayın, kullanıcı ne istediğini zaten biliyor.

```
┌──────────────────────────────────────────────────────────────┐
│  Ne yazalım?                                                 │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ Viktorya dönemi Londra'sında geçen, 10 bölümlük bir    │  │
│  │ polisiye roman...                                      │  │
│  └────────────────────────────────────────────────────────┘  │
│  Şablonlar:  [Roman] [Öykü seçkisi] [Rehber kitap] [Senaryo] │
│                                                              │
│  Uzunluk   ○ Kısa (~15k)  ● Orta (~50k)  ○ Uzun (~100k kelime)│
│  Ton       [karanlık ▾]   Bakış açısı [3. tekil ▾]           │
│                                                              │
│  ▸ Gelişmiş: model, sıcaklık, düşünme seviyesi, iterasyon    │
│                                                              │
│  Tahmini: ~45 dk · ~1.2M token · ~$0.85       [ Yazmaya başla ]│
└──────────────────────────────────────────────────────────────┘
```

Detaylar:

- **Tahmin kutusu** seçimlerle canlı güncellenir. Maliyet sürprizini en baştan öldürür.
- Şablon seçimi prompt alanını **doldurur**, gizlemez — kullanıcı düzenleyebilmeli.
- Boş prompt ile başlatma engellenmez, örnek prompt önerilir (yaratıcı blokajı kırmak
  ürünün işi).

---

## 5.3 Ekran: Canlı koşu (ürünün kalbi)

```
┌─ Polisiye Roman ──────────────── ● yazılıyor · 3/10 bölüm ──┐
│ ┌──────────┬───────────────────────────────┬──────────────┐ │
│ │ DOSYALAR │  chapter_03.md                │ AJAN AKIŞI   │ │
│ │          │                               │              │ │
│ │ 00_plan  │  ## Sisin Altında             │ 🧠 3. bölümün│ │
│ │ bible ✓  │                               │ ritmini      │ │
│ │ ch_01 ✓  │  Thames'in üzerindeki sis o   │ planlıyorum… │ │
│ │  3.240 k │  sabah alışılmadık biçimde    │              │ │
│ │ ch_02 ✓  │  ağırdı▊                      │ 🔧 read_file │ │
│ │  2.980 k │                               │   ch_02.md   │ │
│ │ ch_03 ✍  │                               │ ✓ 2.980 kel. │ │
│ │          │                               │              │ │
│ ├──────────┴───────────────────────────────┴──────────────┤ │
│ │ ▓▓▓▓▓▓▓▓░░░░░░░░ %34  ·  412k token · $0.31 · ~28 dk    │ │
│ │ [⏸ Duraklat] [✍ Yönlendir] [⏹ Durdur]                   │ │
│ └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

### Panel davranışları

**Sol — dosya ağacı.** Her dosyada durum simgesi (✓ tamam, ✍ yazılıyor, ⏳ planlandı) ve
kelime sayısı. Yeni dosya oluştuğunda kısa bir vurgu animasyonu; kullanıcı "ilerliyor"
hissini buradan alır.

**Orta — canlı metin.** `text.delta` olayları doğrudan buraya akar. Kurallar:

- Otomatik kaydırma **yalnızca** kullanıcı en alttaysa; yukarı kaydırdıysa "⤓ Canlıya dön"
  düğmesi çıkar. (Bu küçük detay, uzun akışlarda deneyimi kurtarır.)
- Markdown canlı render edilir; yarım kalan işaretler (` ``` `, `**`) bozuk görünmemeli —
  akış sırasında hoşgörülü bir ayrıştırıcı kullanın.
- 50k+ kelimede sanal kaydırma (yalnızca görünür bölüm DOM'da).

**Sağ — ajan akışı.** İki mod:

- **Sade (varsayılan):** insan diline çevrilmiş adımlar. "2. bölümü okuyor", "Karakter
  notlarını güncelliyor", "3. bölümü yazıyor".
- **Geliştirici:** ham olaylar, araç argümanları, iterasyon numarası, JSON.

Düşünme metni **daraltılabilir** olmalı ve varsayılan olarak son 3 satırı gösterilmeli;
tamamı kullanıcıyı boğar.

**Alt — ilerleme çubuğu.** İlerleme yüzdesi iterasyondan değil, **planlanan dosya sayısına
göre** hesaplanır (`00_plan.md` bunu verir). İterasyon tabanlı yüzde kullanıcıya yalan
söyler. Yanında token, maliyet ve kalan süre tahmini.

### Yönlendirme (steer)

"✍ Yönlendir" tek satırlık bir giriş açar. Gönderilen mesaj akışta ayırt edilebilir bir
kartla görünür ("Sen: 3. bölüm daha karanlık olsun") ve ajan bir sonraki turda uygular.
Gecikme beklentisi arayüzde belirtilmeli: *"Bir sonraki adımda uygulanacak."*

### Onay modu

`confirm_writes` açıksa, ajan yazmadan önce panel bir karta dönüşür:

```
Ajan chapter_04.md yazmak istiyor (3.400 kelime)
[Önizle]  [Onayla]  [Reddet ve not bırak]
```

"Reddet ve not bırak" → gerekçe ajanın bir sonraki turuna girdi olur.

---

## 5.4 Ekran: Okuyucu

- Tek sütun, 68 karakter genişlik, serif gövde yazı tipi, ayarlanabilir punto.
- Bölüm gezinme: sol tarafta içindekiler, `J/K` klavye kısayolları.
- Üstte: toplam kelime, tahmini okuma süresi, son güncelleme.
- Her bölümün altında **"Bu bölümü yeniden yazdır"** eylemi → o dosyaya odaklı küçük bir
  koşu başlatır (tüm romanı değil). Bu, ürünü tek atışlık bir üreticiden düzenlenebilir
  bir stüdyoya çevirir.
- Karanlık mod ve "odak modu" (arayüz kaybolur, sadece metin).

---

## 5.5 Ekran: Hikâye kutsal kitabı

`story_bible.md`'nin yapılandırılmış görünümü: karakter kartları, mekânlar, zaman çizgisi,
tutarlılık notları. Kullanıcı düzenleyebilir; düzenleme bir sonraki koşuda ajanın
bağlamına girer.

Bu ekran güven ekranıdır: *"Ajan neyi hatırlıyor?"* sorusunun görünür cevabı. Kullanıcı
ajanın hafızasını görebildiğinde uzun koşulara güveni belirgin biçimde artar.

---

## 5.6 Durumlar, hatalar, boşluklar

| Durum | Gösterim |
|---|---|
| Yükleniyor | İskelet (skeleton), asla dönen çark tek başına |
| Boş projeler | Örnek prompt'larla dolu bir "başla" kartı |
| Bağlantı koptu | Üstte ince şerit: "Bağlantı koptu — yeniden bağlanılıyor…" Koşu **arkada devam ediyor** yazısı şart |
| Kota hatası | Geri sayımlı yeniden dene, "koşu durmadı" güvencesi |
| API anahtarı geçersiz | Doğrudan ayarlar bağlantısı |
| Bütçe aşıldı | Koşu duraklatılır, "bütçeyi artır ve devam et" tek tık |
| Koşu başarısız | Hata sınıfı + son 10 olay + "kaldığı yerden devam et" |

**Mikrometin ilkesi:** hiçbir hata mesajı `Exception` sınıf adı içermesin. Kullanıcıya ne
olduğu ve ne yapabileceği söylenir; teknik detay "ayrıntılar" altında.

---

## 5.7 Performans hedefleri

| Ölçüt | Hedef |
|---|---|
| İlk anlamlı boyama | < 1.5 sn |
| SSE olayı → ekranda görünme | < 100 ms |
| 100k kelimelik projede okuyucu kaydırma | 60 fps (sanal liste) |
| Sekme arka plandayken CPU | ~0 (akışı biriktir, öne gelince tek seferde uygula) |

`text.delta` olaylarını `requestAnimationFrame` ile toplu uygulayın; her olayda `setState`
çağırmak uzun koşularda tarayıcıyı kilitler.

---

## 5.8 Erişilebilirlik

- Canlı akış bölgesi `aria-live="polite"`, ama **delta'lar için değil** — yalnızca aşama
  değişimlerinde duyuru ("3. bölüm yazılıyor"). Aksi halde ekran okuyucu kullanılamaz hale gelir.
- Tüm eylemler klavyeyle erişilebilir; odak halkaları görünür.
- Renk tek başına anlam taşımaz (durum simgeleri + metin).
- Kontrast AA; karanlık modda da doğrulanır.
- Hareketi azalt tercihi (`prefers-reduced-motion`) tüm animasyonları kapatır.

---

## 5.9 İlk 5 dakika (onboarding)

1. Giriş → API anahtarı iste (BYOK), nereden alınacağını **aynı ekranda** göster.
2. Anahtar doğrulaması anında yapılsın (küçük bir test çağrısı).
3. Hazır bir örnek prompt ile "2 dakikalık demo koşusu" öner: tek kısa öykü. Kullanıcı
   ürünün tamamını 2 dakikada görsün.
4. Demo bitince: "Şimdi bir roman yazdır" yönlendirmesi.

İlk deneyimde uzun bir koşu başlatmayın; 45 dakika bekleyen kullanıcı geri dönmez.
