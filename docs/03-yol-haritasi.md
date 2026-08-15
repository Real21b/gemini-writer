# 3. Yol Haritası

Yedi faz. Her fazın sonunda **çalışan ve gösterilebilir** bir ürün var. Süreler tek bir
geliştiricinin yarı zamanlı (haftada ~15 saat) çalışması varsayımıyla verilmiştir.

| Faz | Ad | Süre | Faz sonunda elinizde ne var |
|---|---|---|---|
| 0 | Stabilizasyon | 3-5 gün | Yalan söylemeyen, kurtarması gerçekten çalışan CLI |
| 1 | Çekirdek yeniden yapılandırma | 1.5-2 hafta | Sunucuya taşınabilir, hafızalı, akış yapan ajan |
| 2 | API katmanı | 1.5 hafta | HTTP üzerinden koşu başlatıp canlı izleyebilme |
| 3 | Web MVP | 2-3 hafta | Tarayıcıdan roman yazdırıp okuyabilme |
| 4 | UX derinliği | 2 hafta | Editör, müdahale, sürümler, dışa aktarma |
| 5 | Çok kullanıcı & üretim | 2 hafta | Giriş, kota, maliyet, dağıtım, izleme |
| 6 | Ürünleşme | sürekli | Şablonlar, kalite ajanı, çoklu model |

---

## Faz 0 — Stabilizasyon (3-5 gün)

**Amaç:** Mimariye dokunmadan, bugün acı veren hataları kapatmak. Yeniden yapılandırma
sırasında "bu davranış eskiden doğru muydu?" sorusunu ortadan kaldırır.

### İşler

1. **B-01 · Kurtarma yolunu onar.** `snapshot_context()` fonksiyonunu ayır; üç çağrı
   yerini (`writer.py:249`, `:420`, `:458`) buna bağla. `compress_context_impl` içinde
   `keep_recent = min(keep_recent, max(0, len(messages) - 1))` normalizasyonu ekle.
2. **B-02 · Yol doğrulaması.** `tools/writer.py` içine `resolve_in_workspace` ekle;
   dizin dışına yazmayı ve uzantı dışını reddet.
3. **B-06 · Yeniden deneme.** `tenacity` veya 20 satırlık üstel geri çekilme; kalıcı/geçici
   hata ayrımı; 5 ardışık hatada temiz çıkış.
4. **B-07 · Token muhasebesi.** `response.usage_metadata`'yı kullan; `count_tokens`'ı
   döngüden çıkar.
5. **B-09 · Bitiş bayrağı.** `completed = True` ile yanlış "MAX ITERATIONS" mesajını kaldır.
6. **B-14 · `except:` → `except Exception:`**, API anahtarı basımını `--verbose` arkasına al.
7. **B-10 · Belge doğruluğu.** README'deki akış iddiasını Faz 1'e kadar "planlanan" olarak
   işaretle; `kimi-writer.py` kalıntılarını temizle; `env.example` dosyasını ekle.
8. **Proje hijyeni.** `pyproject.toml` (ruff + pytest + bağımlılıklar), `tests/` iskeleti,
   GitHub Actions: `ruff check` + `pytest`.

### Kabul kriterleri

- [ ] Uzun bir koşuda Ctrl+C → diskte gerçekten `.context_summary_*.md` var ve `--recover`
      onu yükleyip devam ediyor.
- [ ] `write_file` `"../x.md"` çağrısı hata döndürüyor, dosya oluşmuyor (test var).
- [ ] Ağ hatası enjekte edildiğinde geri çekilme uygulanıyor, iterasyonlar boşa yanmıyor.
- [ ] `ruff check` ve `pytest` yeşil; CI çalışıyor.
- [ ] README'deki her komut kopyala-yapıştır çalışıyor.

---

## Faz 1 — Çekirdek yeniden yapılandırma (1.5-2 hafta)

**Amaç:** Ajanı sunucuya taşınabilir, hafızalı ve akış yapan hale getirmek. Bu faz ürünün
gerçek kalite sıçraması: **ajan artık yazdığını okuyabilir.**

### İşler

1. **`core/` paketini oluştur** (bkz. [02-hedef-mimari.md](02-hedef-mimari.md)).
   `writer.py` → `cli/main.py`, yalnızca olayları terminale basan ince bir katman.
2. **B-03 · `Workspace`** nesnesi; `tools/project.py`'deki globali sil. Araçlar workspace
   enjeksiyonuyla çağrılsın.
3. **B-12 · Araç kaydı.** `@tool` dekoratörü + Pydantic'ten şema üretimi.
4. **B-04 · Yeni araçlar:** `read_file`, `list_files`, `apply_patch`, `read_story_bible`,
   `update_story_bible`.
5. **B-08 · `finish_task`** aracı ve gerçek bitiş tespiti.
6. **B-05 · Bağlam yöneticisi.** Katmanlı bağlam (kalıcı çekirdek / sıcak pencere / soğuk
   arşiv), tur sınırında kesme, `Content` üzerinde sıkıştırma. Eşiği %65'e çek.
7. **Akış.** `generate_content_stream` + olay üreteci; `thinking.delta` / `text.delta`.
8. **Olay veri yolu.** `core/events.py`; runner artık `print` etmiyor.
9. **Sahte LLM ile testler.** Kaydedilmiş yanıt dizileriyle döngüyü API'siz test et.

### Sistem promptu güncellemesi (kalite için kritik)

Yeni promptun zorunlu kılması gerekenler:

- Yazmadan önce **plan dosyası** (`00_plan.md`) ve **hikâye kutsal kitabı**
  (`story_bible.md`) oluştur.
- Her bölümden önce `read_story_bible`, sonra `update_story_bible` çağır.
- Bölüm biterken bir önceki bölümün son 500 kelimesini `read_file` ile oku (geçiş
  tutarlılığı).
- Görev bitince `finish_task` çağır.

### Kabul kriterleri

- [ ] 10 bölümlük bir roman koşusunda karakter isimleri/özellikleri bölümler arası tutarlı
      (elle 3 bölüm örneklemesiyle doğrulanır).
- [ ] Aynı süreçte iki koşu paralel çalışıyor ve dosyaları karışmıyor (test var).
- [ ] Sıkıştırma sonrası araç çağrısı zinciri kırılmıyor; 900K'ya çıkmadan koşu bitiyor.
- [ ] Terminalde düşünme ve metin **canlı akıyor**.
- [ ] `pytest` API anahtarı olmadan tüm çekirdeği kapsıyor.

---

## Faz 2 — API katmanı (1.5 hafta)

**Amaç:** Çekirdeği HTTP'ye açmak. Arayüz yok; `curl` ve OpenAPI dokümanı yeterli.

### İşler

1. **FastAPI iskeleti**, `/health`, OpenAPI şeması.
2. **Veri modeli + migrasyonlar** (SQLModel + Alembic; SQLite ile başla, Postgres'e
   hazır tut). Şema: [04-api-ve-veri-modeli.md](04-api-ve-veri-modeli.md).
3. **Koşu uçları:** `POST /runs`, `GET /runs/{id}`, `POST /runs/{id}/cancel`,
   `POST /runs/{id}/steer`.
4. **SSE ucu:** `GET /runs/{id}/events` — `Last-Event-ID` ile devam.
5. **Dosya uçları:** `GET /projects/{id}/files`, `GET /files/{id}` (+ ham indirme).
6. **Olay kalıcılığı:** her olay DB'ye; kopan bağlantı sonrası tam yeniden oynatma.
7. **Görev yürütücü:** `asyncio.Task` + iptal desteği + süreç kapanırken koşuları
   `interrupted` işaretleme.
8. **Anahtar yönetimi:** sunucu tarafında tek anahtar (Faz 5'te kullanıcı başına).

### Kabul kriterleri

- [ ] `curl -X POST /runs` ile başlatılan koşu, `curl -N /runs/{id}/events` ile canlı izleniyor.
- [ ] Akış ortasında bağlantıyı kes → yeniden bağlan → `Last-Event-ID` sonrası olaylar
      eksiksiz geliyor, tekrar yok.
- [ ] `cancel` çağrısı koşuyu 2 saniye içinde durduruyor ve durum `cancelled` oluyor.
- [ ] Sunucu yeniden başlatıldığında yarım koşular `interrupted` olarak işaretli, dosyalar
      duruyor.

---

## Faz 3 — Web MVP (2-3 hafta)

**Amaç:** Tarayıcıdan roman yazdırma ve okuma. Editör yok, çok kullanıcı yok — **tek
kullanıcı, harika bir izleme deneyimi.**

### İşler

1. Next.js kurulumu, OpenAPI'den tip üretimi (`openapi-typescript`).
2. **Ekran 1 — Projeler:** kart listesi, durum rozetleri, "Yeni yazım" düğmesi.
3. **Ekran 2 — Yeni koşu:** prompt alanı + tür/uzunluk/ton ön ayarları + gelişmiş ayarlar
   (model, iterasyon, bütçe) + tahmini süre ve maliyet.
4. **Ekran 3 — Canlı koşu (ürünün kalbi):** üç panel — sol: dosya ağacı; orta: yazılan
   metin canlı; sağ: ajan akışı (düşünme, araç çağrıları, token/maliyet).
5. **Ekran 4 — Okuyucu:** bölüm bölüm okuma, kelime sayısı, okuma süresi tahmini.
6. **SSE istemcisi:** yeniden bağlanma, olay sıralaması, arka planda sekme davranışı.
7. Boş durumlar, hata durumları, yükleniyor iskeletleri (ilk günden — sonradan eklenmiyor).

### Kabul kriterleri

- [ ] Tarayıcıdan başlatılan koşu, sayfa yenilendikten sonra da canlı izlenebiliyor.
- [ ] 60.000 kelimelik bir projede dosya ağacı ve okuyucu takılmıyor (sanal kaydırma).
- [ ] Mobil ekranda paneller anlamlı biçimde yığılıyor, akış okunabiliyor.
- [ ] Lighthouse erişilebilirlik ≥ 90.

---

## Faz 4 — UX derinliği (2 hafta)

**Amaç:** İzleyiciden **iş ortağına** geçiş. Kullanıcı artık metne dokunabiliyor.

### İşler

1. **Markdown editörü** (CodeMirror 6): kullanıcı düzenlemesi, otomatik kayıt, ajan
   yazarken kilit uyarısı.
2. **Sürüm geçmişi ve geri alma:** her yazma bir sürüm; yan yana fark (diff) görünümü.
3. **Yönlendirme (steer):** koşu sürerken "3. bölümü daha karanlık yap" mesajı; ajan bir
   sonraki turda dikkate alır. Duraklat/devam et.
4. **Onay modu:** "her dosya yazımından önce bana sor" seçeneği; ekle/reddet/düzenle.
5. **`ask_user` desteği:** ajan soru sorduğunda arayüzde belirgin bir kart, cevap
   yazılınca koşu devam eder.
6. **Dışa aktarma:** Markdown (zip), tek dosya birleştirme, PDF, EPUB. Kapak sayfası ve
   içindekiler otomatik.
7. **Hikâye kutsal kitabı görünümü:** karakterler/mekânlar sekmesi, ajanın hafızasını
   kullanıcının da görebildiği yer — güven veren en güçlü ekran.

### Kabul kriterleri

- [ ] Koşu sürerken gönderilen yönlendirme mesajı en geç bir sonraki iterasyonda etkili.
- [ ] Kullanıcı düzenlemesi ile ajan yazımı çakışmıyor; çakışma olursa kullanıcı kazanıyor
      ve uyarılıyor.
- [ ] EPUB çıktısı bir e-okuyucuda içindekiler ile birlikte açılıyor.

---

## Faz 5 — Çok kullanıcı ve üretim (2 hafta)

### İşler

1. **Kimlik doğrulama:** Auth.js (Google + e-posta bağlantısı). Faz 3-4'te tek kullanıcı
   modunun arkasında zaten `user_id` alanı hazır olmalı.
2. **Kullanıcı başına API anahtarı:** ya kullanıcı kendi Gemini anahtarını getirir (BYOK,
   şifreli saklanır) ya da platform anahtarı + kota. **Öneri: ilk sürümde BYOK** — hem
   maliyet hem yasal yükü sıfırlar.
3. **Kota ve bütçe:** koşu başına token tavanı, kullanıcı başına aylık tavan, tavana
   yaklaşınca uyarı, aşınca koşuyu duraklat.
4. **İş kuyruğu:** Redis + RQ/Celery; API ile worker'ı ayır; eşzamanlı koşu sınırı.
5. **Gözlemlenebilirlik:** yapılandırılmış JSON log, Sentry, temel metrikler (koşu süresi,
   başarı oranı, ortalama token, hata sınıfları).
6. **Dağıtım:** Docker Compose (api, worker, web, postgres, redis), tek komutla ayağa
   kalkma; web için Vercel veya aynı compose.
7. **Yedekleme:** veritabanı günlük yedek, dosya deposu S3 + sürümleme.

### Kabul kriterleri

- [ ] İki farklı kullanıcı aynı anda koşu yapıyor; hiçbir veri sızıntısı yok (test var).
- [ ] Bütçe tavanına ulaşan koşu duruyor ve kullanıcı bilgilendiriliyor.
- [ ] `docker compose up` ile temiz bir makinede sistem çalışıyor.

---

## Faz 6 — Ürünleşme (sürekli)

Öncelik sırasına göre fikir havuzu:

1. **Şablonlar:** "Polisiye roman", "çocuk kitabı", "teknik rehber", "senaryo" — hazır
   prompt + yapı + ton ayarları.
2. **Editör ajanı (ikinci geçiş):** yazım bittikten sonra tutarlılık, tekrar, ritim
   denetimi yapan ayrı bir koşu. Kalitede en görünür sıçrama burada.
3. **Çoklu model:** plan için güçlü model, üretim için hızlı model; kullanıcıya maliyet/
   kalite kaydırıcısı.
4. **İşbirliği:** proje paylaşımı, yorumlar, salt-okunur bağlantı.
5. **Sesli okuma / TTS**, **kapak görseli üretimi**, **çeviri koşusu**.
6. **Yayına hazırlık:** KDP uyumlu çıktı, sayfa düzeni, ISBN alanları.

---

## Riskler ve karşı önlemler

| Risk | Etki | Önlem |
|---|---|---|
| Model API'sinde kırıcı değişiklik (`gemini-3-flash-preview` bir önizleme sürümü) | Koşular durur | Model adını yapılandırmaya taşı (B-11), LLM katmanını tek dosyada tut, sözleşme testleri |
| Uzun koşuların maliyeti | Sürpriz fatura | Koşu başına bütçe, canlı maliyet göstergesi, BYOK |
| Uzun metinlerde kalite düşüşü | Ürünün varlık nedeni zarar görür | Story bible + `read_file` (Faz 1), editör ajanı (Faz 6) |
| Yeniden yapılandırmanın uzaması | Motivasyon kaybı | Faz 0/1'de CLI çalışır kalır; her faz bağımsız değer üretir |
| SSE'nin ara sunucularda kesilmesi | Canlı izleme bozulur | Heartbeat yorumu (`:ping`), `Last-Event-ID` ile devam, olayların DB'de kalıcı olması |
