# 1. Mevcut Durum Analizi

Bu bölüm kodun haritasını ve tespit edilen sorunları içerir. Her bulgu `dosya:satır`
referanslıdır; doğrudan iş kalemi olarak kullanılabilir.

> **Not:** Bu analiz Faz 0 çalışması **öncesindeki** kodu anlatır ve bulguların kaynak
> kaydı olarak korunmuştur. **B-01, B-02, B-06, B-07, B-09, B-10, B-14 kapatıldı** —
> ne yapıldığı [FAZ-0-TAMAMLANDI.md](FAZ-0-TAMAMLANDI.md) içinde. Kalan bulgular
> (B-03, B-04, B-05, B-08, B-11, B-12, B-13) Faz 1'de kapanacak.

---

## 1.1 Depo haritası

```
gemini-writer/
├── writer.py              470 satır — CLI girişi + ajan döngüsü (tüm orkestrasyon burada)
├── utils.py               153 satır — token sayımı + araç şemaları + sistem promptu
├── tools/
│   ├── __init__.py         15 satır — araç dışa aktarımları
│   ├── project.py         101 satır — proje klasörü (global durum burada)
│   ├── writer.py           62 satır — dosya yazma (create/append/overwrite)
│   └── compression.py     182 satır — bağlam özetleme + özet dosyası
├── requirements.txt         3 bağımlılık (google-genai, httpx, python-dotenv)
├── README.md
└── LICENSE                MIT + atıf şartı
```

Test yok, `pyproject.toml` yok, lint/format yapılandırması yok, CI yok, `env.example`
yok (README'de referans veriliyor ama dosya depoda değil).

## 1.2 Çalışma akışı (bugünkü)

```
kullanıcı promptu
   │
   ▼
writer.py:main()
   ├─ API anahtarı kontrolü ................ writer.py:124
   ├─ genai.Client                          writer.py:137
   └─ döngü: 1..300 ....................... writer.py:178
        ├─ count_tokens (her iterasyonda ağ çağrısı)   writer.py:185
        ├─ eşik aşıldıysa sıkıştır .................... writer.py:189
        ├─ her 50 iterasyonda yedek ................... writer.py:232
        ├─ generate_content (akışsız) ................. writer.py:271
        ├─ parçaları ayrıştır (thought / text / call) . writer.py:288
        ├─ araç çağrısı yoksa → "TAMAMLANDI", çık ..... writer.py:334
        └─ araçları çalıştır, sonuçları geri besle .... writer.py:346
```

Mimarinin doğru yaptığı şey: **model yanıtının `Content` nesnesi olduğu gibi geçmişe
ekleniyor** (`writer.py:328`). Bu, Gemini'nin fonksiyon çağrılarında beklediği
`thought_signature` alanını korur — sık yapılan bir hatadan kaçınılmış.

---

## 1.3 Bulgular

Önem: **K** = Kritik (veri kaybı/güvenlik), **Y** = Yüksek, **O** = Orta, **D** = Düşük.

### B-01 · K · Yedekleme ve kurtarma yolu hiç çalışmıyor

`compress_context_impl` şu erken dönüşle başlıyor:

```python
# tools/compression.py:41
if len(messages) <= keep_recent + 1:
    return {"compressed_messages": messages, "summary_file": None, ...}
```

Üç çağrı yerinin üçü de `keep_recent=len(simple_messages)` gönderiyor:

- otomatik yedek — `writer.py:249`
- Ctrl+C ile kesinti kaydı — `writer.py:420`
- maksimum iterasyon kaydı — `writer.py:458`

`len(messages) <= len(messages) + 1` **her zaman doğru** olduğu için bu üç yol da hiçbir
şey yazmadan dönüyor. Sonuç: README'de anlatılan "her 50 iterasyonda yedek" ve "Ctrl+C
ile güvenli kayıt" özellikleri fiilen yok. Kullanıcı 4 saatlik bir romanı iptal ettiğinde
`--recover` için dosya bulamaz.

**Çözüm:** Özet üretimini "sıkıştırma" işleminden ayırın. `snapshot_context()` adlı ayrı
bir fonksiyon tüm geçmişi özetleyip dosyaya yazsın; `compress_context()` sadece bağlam
kırpma işini yapsın. Ayrıca `keep_recent` değeri `len(messages)` gibi anlamsız bir değer
alırsa `min(keep_recent, len(messages) - 1)` ile normalize edilsin.

### B-02 · K · `write_file` dizin dışına yazabiliyor (path traversal)

```python
# tools/writer.py:32
file_path = os.path.join(project_folder, filename)
```

`filename` hiç doğrulanmıyor. Model `"../../../etc/cron.d/x.md"` üretirse dosya proje
klasörünün dışına yazılır. CLI'da bu "modelin hatası"; HTTP sunucusunda bu **uzaktan
dosya yazma açığı**dır. Faz 2'ye geçmeden kapatılmalı.

**Çözüm:**

```python
from pathlib import Path

def resolve_in_workspace(root: Path, filename: str) -> Path:
    candidate = (root / filename).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError(f"Geçersiz dosya yolu: {filename}")
    return candidate
```

Ek olarak dosya adı uzunluğu, gizli dosya (`.` ile başlama) ve uzantı beyaz listesi
kontrol edilmeli.

### B-03 · K · Aktif proje klasörü global değişkende

```python
# tools/project.py:11
_active_project_folder: Optional[str] = None
```

Modül düzeyinde global durum. Tek kullanıcılı CLI'da sorun değil; ama:

- Aynı süreçte iki koşu → ikisi de aynı klasöre yazar.
- Web sunucusunda iki kullanıcı → **A kullanıcısı B'nin romanına bölüm ekler.**
- Testler birbirini kirletir (sıralamaya bağlı testler).

**Çözüm:** `Workspace` nesnesi (kök dizin + proje adı + yazma politikası) ve araçların
bu nesneyi parametre olarak alması. Bu, Faz 1'in omurgasıdır; detay
[02-hedef-mimari.md](02-hedef-mimari.md#21-çekirdek-core-paketi).

### B-04 · Y · Ajan yazdığı hiçbir şeyi okuyamıyor

Araç seti üç fonksiyondan ibaret (`utils.py:46-95`): `create_project`, `write_file`,
`compress_context`. `read_file`, `list_files`, `search` yok.

Sonuç: 12 bölümlük bir romanda 7. bölümü yazarken ajanın 3. bölümdeki bilgiye erişmesinin
tek yolu, o metnin hâlâ bağlamda olması. Bağlam sıkıştırması devreye girdiği anda
(ki 900K eşiği zaten yüksek) karakter isimleri, göz rengi, zaman çizgisi kayar. Bu, uzun
metin üreten ajanlarda **birinci sıradaki kalite şikâyeti**dir.

**Çözüm (Faz 1):** `read_file`, `list_files`, `apply_patch` araçları + kalıcı bir
**hikâye kutsal kitabı** (`story_bible.md`): karakterler, mekânlar, zaman çizgisi,
tutarlılık notları. Sistem promptu her bölüm öncesi bu dosyayı okumayı zorunlu kılsın.

### B-05 · Y · Bağlam sıkıştırması araç çağrılarını ve imzaları yok ediyor

```python
# writer.py:209-221
for msg in compression_result["compressed_messages"]:
    ...
    new_contents.append(types.Content(role=role, parts=[types.Part.from_text(...)]))
```

Sıkıştırma sonrası geçmiş **sadece düz metne** indirgeniyor. Kaybolanlar:
`function_call` parçaları, `function_response` parçaları ve `thought_signature`.
Ayrıca `role` normalizasyonu ard arda iki `user` mesajı üretebiliyor. Yani sıkıştırma
tetiklendiği anda ajanın araç çağrı zinciri bozulabilir — hatanın sinsi tarafı, bunun
sadece uzun koşularda ortaya çıkmasıdır.

**Çözüm:** Sıkıştırmayı `Content` nesneleri üzerinde yapın; özeti tek bir `user` mesajına
koyun, **son N turu ham `Content` olarak koruyun** (metne çevirmeden). Kesme noktası her
zaman tamamlanmış bir tur sınırında olmalı: bir `function_call` içeren model mesajı,
kendi `function_response`'undan ayrılmamalı.

### B-06 · Y · Hata durumunda kontrolsüz yeniden deneme

```python
# writer.py:430-433
except Exception as e:
    print(f"\n✗ Error during iteration {iteration}: {e}")
    continue
```

429 (kota) veya 503 hatasında döngü bekleme yapmadan tekrar çağrı atıyor; 300 iterasyon
saniyeler içinde tükenebilir ve kota daha da kötüleşir. Ayrıca kalıcı hata (geçersiz API
anahtarı) ile geçici hata ayırt edilmiyor.

**Çözüm:** Üstel geri çekilme + jitter, hata sınıflandırması (kalıcı → çık, geçici →
yeniden dene), ardışık hata sayacı (örn. 5 üst üste hata → koşuyu `failed` yap).

### B-07 · O · Her iterasyonda ek `count_tokens` ağ çağrısı

`writer.py:185` her turda tüm geçmişi API'ye gönderip token saydırıyor. Bu, tur başına
fazladan bir gidiş-dönüş ve gecikme demek. Oysa `generate_content` yanıtı zaten
`usage_metadata` içinde gerçek sayımı döndürüyor.

**Çözüm:** Token sayısını yanıttan okuyun; `count_tokens`'ı sadece koşu başında bir kez
ve sıkıştırma sonrası doğrulama için kullanın.

### B-08 · O · "Görev tamamlandı" tespiti güvenilmez

```python
# writer.py:334
if not function_calls_list:
    print("✅ TASK COMPLETED"); break
```

Model bir soru sorarsa, ara özet yazarsa ya da düşünürken araç çağırmayı unutursa koşu
"tamamlandı" sayılıp yarım romanla biter. Kullanıcıya hiçbir uyarı gitmez.

**Çözüm:** Açık bir `finish_task(summary, files_written)` aracı tanımlayın; koşu ancak bu
araç çağrıldığında `completed` olsun. Araçsız metin dönerse: (a) planlanan dosyalar
yazılmış mı kontrol et, (b) yazılmadıysa "devam et" mesajı ile bir tur daha ver, (c) iki
kez üst üste boş dönerse `needs_input` durumuna geç ve kullanıcıya sor.

### B-09 · O · Son iterasyonda yanlış "MAX ITERATIONS" mesajı

`writer.py:436` döngüden sonra `iteration >= MAX_ITERATIONS` kontrolü yapıyor. Görev tam
300. iterasyonda başarıyla bittiyse `break` sonrası bu koşul yine doğru olur ve kullanıcı
başarılı koşuyu "limite takıldı" sanır. `break` öncesi bir `completed = True` bayrağı
yeterli.

### B-10 · O · README ile kod uyuşmuyor

| README iddiası | Gerçek |
|---|---|
| "Real-Time Streaming — karakter karakter izleyin" (README:9, 156-161) | `writer.py:271` **akışsız** `generate_content` kullanıyor; kodda `# Use non-streaming` notu var |
| "Automatic context summaries every 50 iterations" (README:108) | B-01 nedeniyle hiç yazılmıyor |
| `cp env.example .env` (README:45) | `env.example` depoda yok |
| Proje ağacı `kimi-writer/` (README:114) | Depo adı `gemini-writer` |

Ayrıca yardım metinleri ve kurtarma ipuçları hâlâ `kimi-writer.py` diyor
(`writer.py:71-74`, `writer.py:425`, `writer.py:463`). Bu, projenin bir çatallama
(fork) olmasından kalan iz; kullanıcıya yanlış komut veriyor.

### B-11 · O · Yapılandırma kodun içine gömülü

`MODEL_NAME`, `MAX_ITERATIONS`, `TOKEN_LIMIT`, `COMPRESSION_THRESHOLD` (`writer.py:31-35`),
`temperature=1.0` ve `thinking_level="HIGH"` (`writer.py:257-264`) sabit. Model değiştirmek
için kod düzenlemek gerekiyor; koşu bazında ayar imkânsız.

**Çözüm:** `pydantic-settings` tabanlı `Settings` + koşu başına `RunConfig` (model,
sıcaklık, düşünme seviyesi, iterasyon limiti, bütçe).

### B-12 · D · `utils.py` üç ayrı sorumluluk taşıyor

Token sayımı + araç şemaları + sistem promptu aynı dosyada. Araç şemaları elle yazıldığı
için imza ile şemanın birbirinden kayması an meselesi (`utils.py:46-95` ile
`tools/writer.py:10` arasındaki bağ derleyici tarafından denetlenmiyor).

**Çözüm:** `core/tools/` altında her araç kendi şemasını + uygulamasını + testini taşısın;
kayıt (registry) dekoratörle yapılsın, şema Pydantic modelinden üretilsin.

### B-13 · D · `append` modu var olmayan dosyayı sessizce yaratıyor

`tools/writer.py:46` `open(..., 'a')` kullanıyor; ajan yanlış dosya adına eklerse hata
almak yerine yeni bir dosya oluşur ve bu fark edilmez.

### B-14 · D · Bare `except` ve gürültülü günlükleme

`writer.py:426`'daki `except:` `KeyboardInterrupt`/`SystemExit` dahil her şeyi yutuyor.
Ayrıca API anahtarının ilk/son 4 karakteri stdout'a basılıyor (`writer.py:132`) — CLI'da
kabul edilebilir, ancak sunucu günlüklerinde asla olmamalı.

---

## 1.4 Öncelik sırası

Faz 0'da kapatılacaklar (hepsi küçük, hepsi bugün acı veriyor):

1. B-01 — kurtarma tamamen bozuk
2. B-02 — sunucuya geçmeden önce şart
3. B-09, B-10, B-14 — kullanıcıya yalan söyleyen davranışlar
4. B-06, B-07 — kota ve gecikme

Faz 1'e devredilenler: B-03, B-04, B-05, B-08, B-11, B-12, B-13.
