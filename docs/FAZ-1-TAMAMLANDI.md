# Faz 1 — Uygulama Raporu

Faz 1 tamamlandı: ajan çekirdeği arayüzden ayrıldı, global durum kaldırıldı, ajana hafıza
(okuma araçları + hikâye kutsal kitabı) verildi, gerçek akış (streaming) eklendi ve bağlam
sıkıştırması araç çağrılarını bozmayacak şekilde yeniden yazıldı.

**Özet:** 144 test, %93 satır kapsamı, `ruff check` temiz. Faz 0'daki 88 testin davranışsal
kapsamı korundu; testler yeni API'ye taşındı.

---

## Yeni yapı

```
writer.py            → sadece giriş noktası (12 satır)
core/
  config.py          Settings (ortam) + RunConfig (koşu bazlı)
  events.py          EventType + Event + EventEmitter (seq numaralı akış)
  workspace.py       Dosya sistemine dokunan tek yer
  llm.py             Gemini sarmalayıcı: akış, yeniden deneme, kullanım
  context.py         Sıkıştırma, tur sınırı, anlık görüntü
  runner.py          Ajan döngüsü — olay üretir, asla print etmez
  prompts.py         Sistem promptu + özetleme promptu
  tools/             base (registry) · files · bible · control
cli/
  main.py            Argümanlar, koşu kurulumu, çıkış kodları
  renderer.py        Olay akışını terminale basar
```

`tools/` ve `utils.py` kaldırıldı; içerikleri `core/` altına taşındı. `python writer.py "..."`
komutu aynen çalışmaya devam ediyor.

---

## Kapatılan bulgular

### B-03 · Global proje klasörü kaldırıldı

`tools/project.py:_active_project_folder` globali yerine `Workspace` nesnesi. Her koşu kendi
örneğini taşıyor; araçlar `ToolContext(workspace=...)` üzerinden erişiyor.

Testle kanıtlandı (`test_two_workspaces_do_not_share_state`): aynı süreçte iki workspace
farklı projelere yazıyor ve dosyaları karışmıyor. Faz 2'deki HTTP sunucusunun ön koşulu
buydu.

### B-04 · Ajan artık yazdığını okuyabiliyor

Yeni araçlar:

| Araç | Ne işe yarıyor |
|---|---|
| `read_file` | Tüm dosyayı veya `tail_chars` ile sadece sonunu okur (bölüm geçişi tutarlılığı) |
| `list_files` | Dosya envanteri + kelime sayıları |
| `apply_patch` | Tek ve benzersiz bir pasajı değiştirir; tüm bölümü yeniden yazmaya gerek kalmaz |
| `read_story_bible` / `update_story_bible` | Kalıcı hafıza: künye, karakterler, mekânlar, zaman çizgisi |

`story_bible.md` bölüm bazlı birleştirme ile güncelleniyor (`append`/`replace`), yani ajan
bir bölümü güncellerken diğerlerini ezmiyor. Sistem promptu her bölüm öncesi kutsal kitabı
okumayı, sonrasında güncellemeyi zorunlu kılıyor.

**Neden önemli:** bağlam sıkıştırıldığında bile kutsal kitap ve diskteki dosyalar duruyor.
Ajanın hafızası artık bağlam penceresine değil, diske bağlı.

### B-05 · Sıkıştırma artık araç çağrılarını yok etmiyor

Eski davranış: sıkıştırma anında tüm geçmiş düz metne çevriliyordu → `function_call`,
`function_response` ve `thought_signature` kayboluyordu.

Yeni davranış (`core/context.py`):

- Son N tur **ham `Content` olarak** korunuyor (imzalar sağlam).
- Yalnızca eski önek özetleniyor.
- Kesme noktası daima tur sınırında: `is_boundary()` bir `function_response` taşıyan
  kullanıcı mesajının önünden kesmeyi reddediyor, `find_cut_point()` en yakın güvenli
  indekse geri kayıyor.
- Özet mesajı "kalıcı çekirdek" taşıyor: özgün istek + özet + güncel hikâye kutsal kitabı +
  diskteki dosya listesi.
- Eşik %90 → **%65**'e çekildi (`compression_ratio`). 900K token'lık istek hem pahalı hem
  yavaş, hem de modelin dikkati dağılıyor.

Testlerle kanıtlandı: `test_compression_never_orphans_a_function_call`,
`test_compression_keeps_recent_turns_as_raw_content`.

### B-08 · Bitiş tespiti gerçek

`finish_task(summary, files_written)` aracı eklendi ve koşu **yalnızca** bu araç
çağrıldığında `run.completed` oluyor. Araçsız metin dönüşü artık:

1. bir kez "devam et" mesajıyla dürtülüyor (`CONTINUE_NUDGE`),
2. üst üste tekrarlanırsa `run.needs_input` ile duruyor ve kullanıcıya soruluyor.

Eski davranışta bu durum "✅ TASK COMPLETED" yazıp yarım romanla çıkıyordu.

### B-11 · Yapılandırma dışarı alındı

`RunConfig`: model, sıcaklık, düşünme seviyesi, iterasyon limiti, token limiti, sıkıştırma
oranı, yedek aralığı, akış açık/kapalı, deneme limitleri. CLI bayrakları: `--model`,
`--max-iterations`, `--temperature`, `--thinking`, `--output-dir`, `--no-stream`.
`Settings.from_env` ortam değişkenlerini okuyan tek yer (`GEMINI_API_KEY`,
`GEMINI_WRITER_MODEL`, `GEMINI_WRITER_OUTPUT_DIR`).

### B-12 · Araç şemaları tek kaynaktan

`@tool(name, description, args_model)` dekoratörü + `pydantic_to_genai_schema()`. Şema artık
Pydantic modelinden üretiliyor: `Literal` → enum, `Optional[...]` → tip, `List[str]` → dizi.
Elle yazılan ikinci bir şema kalmadı, dolayısıyla imza/şema kayması imkânsız.

Argüman doğrulaması da buraya taşındı: eksik ya da hatalı argüman modele okunabilir bir hata
mesajı olarak dönüyor, koşuyu düşürmüyor.

### B-13 · `append` artık sessizce dosya yaratmıyor

`Workspace.write(..., "append")` dosya yoksa hata veriyor; modelin yazım hatası fark
edilmeden ikinci bir dosya oluşturmuyor.

---

## Yeni yetenekler

### Gerçek akış (streaming)

`GeminiLLM.stream_turn` `generate_content_stream` kullanıyor ve parçaları **sırayla
biriktirip** tek bir `Content` olarak geçmişe ekliyor — böylece görüntüde delta akarken
geçmişte imzalar korunuyor. `--no-stream` ile kapatılabiliyor; iki mod da aynı dosyaları
üretiyor (testle doğrulandı).

README'nin Faz 0'da "uygulanmadı" diye işaretlenen akış iddiası artık doğru.

### Olay akışı

Runner `print` etmiyor; `run.started`, `iteration.started`, `thinking.delta`, `text.delta`,
`tool.call`, `tool.result`, `file.written`, `usage.updated`, `context.compressed`,
`snapshot.saved`, `warning`, `run.completed`, `run.failed`, `run.needs_input` olayları
üretiyor. Her olay artan `seq` taşıyor — Faz 2'deki SSE `Last-Event-ID` desteği bunun
üstüne oturacak.

`cli/renderer.py` bu akışın ilk tüketicisi. Delta'lar tek satırda akıyor, blok olay
gelmeden önce satır kapatılıyor.

### Çıkış kodları

`0` tamamlandı (veya Ctrl+C ile anlık görüntü alındı), `1` başarısız, `2` kullanıcı girdisi
gerekiyor. Otomasyon için anlamlı.

---

## Kabul kriterleri — doğrulama

| Kriter | Durum | Nasıl |
|---|---|---|
| Aynı süreçte iki koşu paralel, dosyalar karışmıyor | ✅ | `test_two_workspaces_do_not_share_state` |
| Sıkıştırma sonrası araç çağrı zinciri kırılmıyor | ✅ | `test_compression_never_orphans_a_function_call`, `test_cut_point_snaps_backwards_to_a_safe_index` |
| Terminalde düşünme ve metin canlı akıyor | ✅ | `test_streaming_deltas_are_emitted`, `test_renderer_streams_deltas_on_one_line` |
| `pytest` API anahtarı olmadan tüm çekirdeği kapsıyor | ✅ | 144 test, %93 kapsam, ağ çağrısı yok |
| Bölümler arası tutarlılık altyapısı | ✅ (yapısal) | `read_file(tail_chars)`, story bible araçları, prompt zorunlulukları — **metin kalitesi gerçek koşuyla ölçülmeli** |

**Doğrulanmayan:** gerçek API ile canlı koşu (bu ortamda anahtar yok). Özellikle
`generate_content_stream` davranışı sahte istemciyle test edildi; ilk canlı koşuda akışın
ve `thought_signature` korunumunun gözlenmesi önerilir. Sorun çıkarsa `--no-stream` aynı
sonucu üreten güvenli yol olarak duruyor.

---

## Faz 2'ye hazırlık

Faz 2 (FastAPI + SSE) için gereken her şey yerinde:

- `AgentRunner.run()` bir olay üreteci → SSE'ye doğrudan bağlanır.
- `Workspace` koşu bazlı → çok kullanıcı mümkün.
- `RunConfig` → istek gövdesinden doldurulabilir.
- Olay `seq` → `Last-Event-ID` ile devam.
- Kalan tek uyarlama: runner'ı `async` sarmalayıcıya almak veya thread'de çalıştırmak.
