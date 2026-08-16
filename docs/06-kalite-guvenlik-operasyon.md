# 6. Kalite, Güvenlik ve Operasyon

---

## 6.1 Test stratejisi

LLM ajanlarında en sık yapılan hata: "test edilemez, çünkü model rastgele." Test edilecek
olan modelin çıktısı değil, **döngünün davranışı**dır.

### Katmanlar

| Katman | Kapsam | Araç |
|---|---|---|
| Birim | `Workspace` yol güvenliği, araç uygulamaları, bağlam kesme mantığı, token muhasebesi | pytest |
| Sahte LLM | Kaydedilmiş yanıt dizileriyle tüm ajan döngüsü | pytest + `FakeLLM` |
| Sözleşme | Olay şeması, OpenAPI şeması geriye dönük uyumluluk | schemathesis |
| API | Koşu yaşam döngüsü, SSE devamı, iptal | httpx + pytest-asyncio |
| E2E | "Prompt gir → dosya oluştu → okuyucuda görünüyor" | Playwright |
| Duman (canlı) | Gerçek API ile 1 kısa öykü, günde bir | ayrı CI işi |

### FakeLLM deseni

```python
class FakeLLM:
    """Önceden yazılmış tur dizisini sırayla döndürür."""
    def __init__(self, turns): self.turns, self.i = turns, 0
    async def stream_turn(self, contents, config):
        turn = self.turns[self.i]; self.i += 1
        for ev in turn: yield ev
```

Bununla test edilecek senaryolar:

- Araç hatası döndüğünde ajan toparlanıyor mu?
- `finish_task` gelmeden metin dönerse koşu bitmiyor, doğru şekilde devam ediyor mu? (B-08)
- Bağlam eşiği aşıldığında sıkıştırma tur sınırında mı kesiyor? (B-05)
- İptal isteği geldiğinde mevcut tur tamamlanıp anlık görüntü alınıyor mu?
- Ardışık 5 hatadan sonra koşu `failed` oluyor mu? (B-06)

### Kalite değerlendirmesi (ürün seviyesi)

Otomatik testler metnin *iyi* olduğunu söyleyemez. Basit ve ucuz bir ölçüm seti kurun:

- **Yapısal:** hedef kelime sayısına yakınlık, bölüm uzunluk dağılımı, boş/çok kısa dosya var mı.
- **Tutarlılık:** karakter adları ve özelliklerinin bölümler arası çelişkisi (LLM-yargıç ile
  örnekleme; 5 bölümde bir).
- **Tekrar:** n-gram tekrar oranı, aynı cümle kalıplarının sıklığı.

Bunları koşu sonunda bir "kalite raporu" olarak sakla; sürüm sürüm karşılaştırılabilir olsun.

---

## 6.2 Güvenlik

### Öncelikli açıklar

| Konu | Risk | Önlem |
|---|---|---|
| Dosya yolu (B-02) | Çalışma alanı dışına yazma | `Workspace.resolve()`, uzantı beyaz listesi, boyut sınırı |
| Model çıktısının render edilmesi | Markdown içinde XSS | Sunucu tarafı temizleme (sanitize), ham HTML kapalı |
| API anahtarları | Sızıntı | Şifreli saklama, loglara asla yazma, istemciye asla gönderme |
| Prompt enjeksiyonu | Kullanıcı prompt'u ajanı yönlendirir | Ajanın yetkisi zaten sadece kendi çalışma alanına yazmak; ağ/kabuk erişimi **yok** |
| Kaynak tüketimi | Sonsuz koşu, disk dolması | Koşu başına token/iterasyon/disk kotası, kullanıcı başına eşzamanlılık sınırı |
| Yetkilendirme | Başkasının projesini okuma | Her sorguda `user_id` filtresi; testle doğrulanır |
| SSE ile veri sızıntısı | Kimliksiz akış dinleme | Olay ucu da kimlik doğrulamalı; koşu sahibi kontrolü |

### Ajan yetki sınırı ilkesi

Ajan **yalnızca** kendi `Workspace`'ine yazabilir. Kabuk komutu, ağ isteği, keyfi dosya
okuma araçları eklemeyin. Bu sınır korunduğu sürece prompt enjeksiyonunun etki alanı
"kötü roman yazmak" ile sınırlı kalır.

---

## 6.3 Maliyet yönetimi

Uzun metin üretimi bu ürünün en büyük değişken maliyeti. Üç kademeli kontrol:

1. **Koşu bütçesi:** kullanıcı başlatırken tavan belirler; tavan aşılırsa koşu duraklar
   (iptal edilmez — kullanıcı artırıp devam edebilir).
2. **Kullanıcı kotası:** aylık token tavanı; %80'de uyarı.
3. **Yapısal tasarruf:**
   - Bağlam eşiğini düşür (%65) — her turda 900K token göndermek en pahalı hatadır.
   - `apply_patch` ile tam dosya yeniden yazımından kaçın.
   - Planlama turlarında düşünme seviyesi HIGH, üretim turlarında düşük/kapalı.
   - Tekrarlanan sistem promptu + story bible için **prompt önbelleği** kullan.

Maliyet tahmini tek bir yerde (`core/pricing.py`) tutulmalı ve model fiyatı yapılandırmadan
okunmalı; koda gömülü fiyat eskir.

---

## 6.4 Gözlemlenebilirlik

**Yapılandırılmış log (JSON):** her satırda `run_id`, `user_id`, `iteration`, `event_type`.
Bir kullanıcı "romanım yarım kaldı" dediğinde `run_id` ile tüm hikâye okunabilmeli.

**Metrikler:**

- `runs_started` / `runs_completed` / `runs_failed` (hata tipine göre)
- Koşu süresi ve iterasyon sayısı dağılımı (p50/p95)
- Koşu başına token ve maliyet
- Araç çağrısı sayısı ve hata oranı (araç bazında)
- Bağlam sıkıştırma sıklığı — sık sıkıştırma = bağlam stratejisi bozuk sinyali

**Uyarılar:** başarısızlık oranı %10'u aşarsa, p95 koşu süresi iki katına çıkarsa, kota
hataları artarsa.

---

## 6.5 CI/CD

```yaml
# .github/workflows/ci.yml (özet)
jobs:
  python:
    steps:
      - uses: actions/checkout@v4
      - run: pipx install uv && uv sync
      - run: uv run ruff check . && uv run ruff format --check .
      - run: uv run mypy core api
      - run: uv run pytest --cov=core --cov-fail-under=70
  web:
    steps:
      - run: npm ci && npm run lint && npm run typecheck && npm run build
```

Ek işler: haftalık bağımlılık güncellemesi (Dependabot), gizli anahtar taraması, günlük
canlı duman testi (ayrı iş, gerçek API anahtarı ile, kısa öykü).

---

## 6.6 Dağıtım

```yaml
# docker/compose.yaml (özet)
services:
  api:      # FastAPI — uvicorn
  worker:   # koşuları yürüten süreç
  web:      # Next.js
  db:       # postgres:16
  redis:    # kuyruk + pub/sub
volumes:
  projects: # üretilen .md dosyaları (üretimde S3'e taşınır)
```

Notlar:

- **Worker'ı API'den ayırın** (Faz 5). API yeniden başlatıldığında koşular ölmemeli.
- Kapanışta (SIGTERM) çalışan koşular `interrupted` işaretlenir ve bağlam anlık görüntüsü
  alınır — Faz 0'da düzeltilen B-01 burada karşılığını verir.
- Dosya deposu kalıcı hacimde; konteyner ile birlikte silinmemeli.
- Veritabanı günlük yedek, dosya deposu sürümlemeli S3.

---

## 6.7 Teknik borç kaydı

Rehber uygulanırken kapanacak borçların özeti (detay
[01-mevcut-durum-analizi.md](01-mevcut-durum-analizi.md)):

| Kod | Konu | Kapanacağı faz |
|---|---|---|
| B-01 | Kurtarma/yedekleme çalışmıyor | 0 |
| B-02 | Dosya yolu doğrulaması | 0 |
| B-06 | Yeniden deneme ve geri çekilme | 0 |
| B-07 | Gereksiz `count_tokens` çağrısı | 0 |
| B-09 | Yanlış "max iterations" mesajı | 0 |
| B-10 | README–kod uyumsuzluğu | 0 |
| B-14 | Bare `except`, log hijyeni | 0 |
| B-03 | Global proje klasörü | 1 |
| B-04 | Okuma araçlarının yokluğu | 1 |
| B-05 | Sıkıştırmanın imzaları bozması | 1 |
| B-08 | Bitiş tespiti | 1 |
| B-11 | Gömülü yapılandırma | 1 |
| B-12 | `utils.py` sorumluluk karmaşası | 1 |
| B-13 | `append` sessiz dosya oluşturma | 1 |

> Tablodaki borçların tamamı kapatıldı: Faz 0 ([rapor](FAZ-0-TAMAMLANDI.md)) ve
> Faz 1 ([rapor](FAZ-1-TAMAMLANDI.md)).
