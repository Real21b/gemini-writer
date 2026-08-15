# Gemini Writer — Geliştirme Rehberi

Bu klasör, `gemini-writer` projesini bugünkü halinden (tek dosyalık, tek kullanıcılı bir
CLI ajanı) **çok kullanıcılı, gerçek zamanlı ve yüksek kullanıcı deneyimli bir fullstack
yazım stüdyosuna** taşımak için hazırlanmış katmanlı bir yol haritasıdır.

Rehber bilinçli olarak **aşamalı (incremental)** kurgulanmıştır: her faz tek başına
çalışan, kullanılabilir bir ürün bırakır. Hiçbir fazda "3 hafta boyunca hiçbir şey
çalışmıyor" durumu oluşmaz.

## Belgeler

| # | Belge | İçerik |
|---|-------|--------|
| 1 | [01-mevcut-durum-analizi.md](01-mevcut-durum-analizi.md) | Kod taraması, mimari haritası, tespit edilen 14 sorun (dosya:satır referanslı) |
| 2 | [02-hedef-mimari.md](02-hedef-mimari.md) | Hedef fullstack mimari, çekirdek/paket ayrımı, olay (event) protokolü |
| 3 | [03-yol-haritasi.md](03-yol-haritasi.md) | Faz 0→6 yol haritası, işler, kabul kriterleri, tahmini süreler |
| 4 | [04-api-ve-veri-modeli.md](04-api-ve-veri-modeli.md) | REST + SSE sözleşmesi, veritabanı şeması, durum makinesi |
| 5 | [05-frontend-ux.md](05-frontend-ux.md) | Arayüz mimarisi, ekran ekran UX tasarımı, etkileşim kuralları |
| 6 | [06-kalite-guvenlik-operasyon.md](06-kalite-guvenlik-operasyon.md) | Test stratejisi, güvenlik, maliyet kontrolü, dağıtım, gözlemlenebilirlik |
| ✅ | [FAZ-0-TAMAMLANDI.md](FAZ-0-TAMAMLANDI.md) | Faz 0 uygulama raporu: ne yapıldı, hangi bulgu kapandı, kriterler nasıl doğrulandı |

> **Güncel durum:** Faz 0 tamamlandı (88 test, %85 kapsam, CI kurulu). Sıradaki adım Faz 1 —
> `core/` paketi, `Workspace`, okuma araçları ve akış.

## Bir bakışta durum

**Bugün ne var:** `writer.py` içinde 470 satırlık bir ajan döngüsü, 3 araç
(`create_project`, `write_file`, `compress_context`), Gemini 3 Flash ile "düşünme"
modu, terminal çıktısı. Çalışan ve gerçekten iş gören bir prototip.

**Ne eksik:**

1. **Doğruluk:** Yedekleme/kurtarma yolu hiç çalışmıyor (bkz. B-01). Ctrl+C'de bağlam
   kaydedildiği söyleniyor ama dosya yazılmıyor.
2. **Ajan yeteneği:** Ajan yazdığı dosyaları **okuyamıyor**. 15 bölümlük bir romanda
   süreklilik (karakter, olay örgüsü) tutmak matematiksel olarak mümkün değil.
3. **Sunucuya taşınabilirlik:** Aktif proje klasörü **global değişkende** tutuluyor;
   iki kullanıcı aynı anda çalışırsa birbirinin dosyasına yazar.
4. **Deneyim:** Terminalde akan log; ilerleme, maliyet, müdahale, düzenleme, dışa
   aktarma yok.

## Rehberi nasıl kullanmalı

- **Tek başına geliştiriyorsanız:** Faz 0 → 1 → 2 → 3 sırasını bozmayın. Faz 3 sonunda
  gösterilebilir bir ürününüz olur (yaklaşık 5-7 hafta, yarı zamanlı).
- **Hızlı demo gerekiyorsa:** Faz 0'ın sadece B-01/B-02/B-03 maddelerini yapın, sonra
  doğrudan Faz 2 + Faz 3 MVP'sine geçin; Faz 1'i sonra borç olarak kapatın.
- **Her fazın sonunda** ilgili "Kabul kriterleri" listesini gerçekten çalıştırın; bu
  liste bir sonraki fazın ön koşuludur.

## Temel tasarım ilkeleri

Rehber boyunca şu 5 ilkeye sadık kalınır:

1. **Çekirdek arayüzden bağımsızdır.** Ajan mantığı (`core/`) ne CLI'ı ne HTTP'yi bilir;
   sadece olay üretir. CLI ve web bu olayların iki farklı görüntüleyicisidir.
2. **Global durum yok.** Her koşu (run) kendi `Workspace` nesnesini taşır. Bu, tek
   satırlık bir değişiklik değil; çok kullanıcılılığın ön şartıdır.
3. **Her şey olay akışıdır.** Düşünme, metin, araç çağrısı, token sayacı — hepsi tek
   tipli olay şeması. Kurtarma, kayıttan yeniden oynatma (replay) ile yapılır.
4. **Kullanıcı her an müdahale edebilir.** Durdur, yönlendir, reddet, yeniden yaz.
   Ajan otonomdur ama esir almaz.
5. **Maliyet görünürdür.** Token ve tahmini ücret, kullanıcının gördüğü birinci sınıf
   bir veri; sürpriz fatura yok.
