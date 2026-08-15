# Faz 0 — Uygulama Raporu

Faz 0'ın tamamı uygulandı. Bu belge ne yapıldığını, hangi bulgunun nasıl kapatıldığını ve
kabul kriterlerinin nasıl doğrulandığını kaydeder.

**Özet:** 88 test, %85 satır kapsamı, `ruff check` temiz, CI kurulu. Mimari değişmedi —
Faz 1'in yeniden yapılandırması bu sağlam zemin üzerine gelecek.

---

## Kapatılan bulgular

### B-01 · Kurtarma ve yedekleme artık gerçekten çalışıyor

**Sorun:** Üç kayıt yolu da `compress_context_impl(..., keep_recent=len(messages))` çağırıyordu;
`len(messages) <= keep_recent + 1` her zaman doğru olduğu için hiçbir dosya yazılmıyordu.

**Çözüm:** İki işlem birbirinden ayrıldı (`tools/compression.py`):

| Fonksiyon | Görev |
|---|---|
| `snapshot_context(messages, client, model)` | Tüm konuşmayı özetler, `.context_summary_*.md` yazar. Bağlamdan hiçbir şey silmez. |
| `compress_context_impl(..., keep_recent)` | Bağlamı kırpar; `keep_recent` geçmişi aşarsa son yarısını korumaya düşer, sessiz no-op yapmaz. |

Yedek, Ctrl+C ve maksimum iterasyon yolları artık `snapshot_context` kullanıyor
(`writer.py:save_snapshot`). Kurtarma komutu da ekrana doğru dosya yolu ile basılıyor.

**Ek olarak — anlık görüntüler artık işe yarıyor.** Eski `to_simple_messages` yalnızca
metin parçalarını alıyordu; bir ajan koşusu ağırlıklı olarak araç çağrılarından oluştuğu
için özet neredeyse boş kalıyordu. Artık araç çağrıları ve sonuçları da yazılıyor:

```
[Tool call] write_file(filename=chapter_01.md, content=Sisin altında..., mode=create)
[Tool result] write_file: Successfully created file 'chapter_01.md' with 18422 characters.
```

Uzun argümanlar (bir bölümün tamamı) 120 karaktere kırpılıyor — özet kararı taşımalı,
metnin kendisini değil. Bu olmadan `--recover` "hangi bölümler yazılmıştı?" sorusuna
cevap veremiyordu.

### B-02 · Dosya yolu doğrulaması

Yeni modül: `tools/paths.py`.

- Dizin dışına çıkma (`../`, `..\\`, iç içe `chapters/../../`) reddediliyor
- Mutlak yollar reddediliyor
- Uzantı beyaz listesi: `.md`, `.txt`, `.json`, `.yaml`, `.yml`
- Gizli dosyalar, kontrol karakterleri, 200 karakterden uzun adlar, 5 seviyeden derin
  yollar reddediliyor
- Dosya boyutu tavanı 5 MB
- Alt klasörler artık destekleniyor (`chapters/chapter_01.md`) ve güvenli

`write_file` bu doğrulamayı geçemeyen çağrılarda modele hata mesajı döndürüyor; dosya
sistemi hiç açılmıyor.

### B-06 · Yeniden deneme, geri çekilme ve hata sınıflandırması

`utils.call_with_retry`: üstel geri çekilme + jitter (%50-100), varsayılan 5 deneme,
60 sn tavan.

- **Kalıcı hata** (geçersiz anahtar, 400/401/403) → `PermanentAPIError`, anında durur,
  anlık görüntü alır, çıkış kodu 1.
- **Geçici hata** (429/5xx/timeout/bağlantı) → geri çekilerek yeniden dener.
- **Bilinmeyen hata** → geçici sayılır (uzun koşu tek tuhaf hatayla ölmesin), ama deneme
  limiti yine geçerli.
- Üst üste `MAX_CONSECUTIVE_ERRORS = 5` başarısız iterasyon → koşu temiz biter. Eskiden
  beklemesiz `continue` ile 300 iterasyon saniyeler içinde yanıyordu.

### B-07 · Token muhasebesi ücretsiz

`utils.extract_usage` token sayısını yanıtın `usage_metadata` alanından okuyor. Her turdaki
ayrı `count_tokens` ağ çağrısı kaldırıldı; `count_tokens` yalnızca sıkıştırma sonrası
doğrulama için (koşu başına birkaç kez) çağrılıyor.

### B-08 (kısmi) · Araç hataları koşuyu düşürmüyor

Bitiş tespitinin tamamı Faz 1'de (`finish_task`), ancak araç yürütmesi `execute_tool`
içine alındı: modelin hatalı argümanı (`TypeError`) veya aracın kendi istisnası artık
koşuyu çökertmiyor, modele hata mesajı olarak dönüyor.

### B-09 · Yanlış "MAX ITERATIONS" mesajı

`completed` bayrağı eklendi; son iterasyonda başarıyla biten koşu artık "limite takıldı"
demiyor.

### B-10 · Belgeler koda uydu

- README'deki "gerçek zamanlı akış" iddiası, uygulanmadığı açıkça belirtilerek Faz 1'e
  işaretlendi (kod hâlâ akışsız `generate_content` kullanıyor).
- `env.example` eklendi (README'de referans veriliyordu ama depoda yoktu).
- `kimi-writer.py` kalıntıları temizlendi (yardım metni, kurtarma ipuçları, yorum, proje
  ağacı).
- Proje ağacı, hata yönetimi, yazma kum havuzu ve geliştirme bölümleri güncellendi.

### B-14 · Log hijyeni

- `except:` → `except Exception:` / `except OSError:`
- API anahtarı önizlemesi `--verbose` arkasına alındı; varsayılan çıktıda anahtar izi yok.

### Hazırlık: `GEMINI_WRITER_OUTPUT_DIR`

`create_project` çıktı kökü artık ortam değişkeniyle geçersiz kılınabiliyor. Bu, testleri
depo dizinini kirletmekten kurtardı ve Faz 1'deki `Workspace` enjeksiyonunun ilk dikişi.

---

## Proje hijyeni

| Eklenen | İçerik |
|---|---|
| `pyproject.toml` | Bağımlılıklar, dev ekstraları, ruff (line-length 100), pytest yapılandırması, `gemini-writer` konsol betiği |
| `tests/` (6 dosya, 88 test) | Yol güvenliği, dosya yazma, sıkıştırma/anlık görüntü, yeniden deneme, proje klasörü, uçtan uca ajan döngüsü |
| `.github/workflows/ci.yml` | Python 3.10 + 3.12 üzerinde ruff + pytest + kapsam |
| `.gitignore` | Test/lint/build artefaktları |

Testler **API anahtarı gerektirmez**: `tests/conftest.py` içindeki sahte istemci ve
`tests/test_agent_loop.py` içindeki senaryolu model, tüm döngüyü ağ olmadan çalıştırır.

---

## Kabul kriterleri — doğrulama

| Kriter | Durum | Nasıl doğrulandı |
|---|---|---|
| Ctrl+C → diskte gerçek `.context_summary_*.md`, `--recover` onu yüklüyor | ✅ | `test_keyboard_interrupt_saves_a_recovery_snapshot`, `test_snapshot_writes_a_recovery_file` |
| `write_file("../x.md")` hata döndürüyor, dosya oluşmuyor | ✅ | `test_traversal_does_not_write_outside` + 12 yol testi |
| Ağ hatasında geri çekilme uygulanıyor, iterasyonlar boşa yanmıyor | ✅ | `test_transient_errors_are_retried_then_the_run_continues`, `test_run_stops_after_consecutive_failures`, `test_backoff_grows_and_stays_bounded` |
| `ruff check` ve `pytest` yeşil, CI çalışıyor | ✅ | 88 test / %85 kapsam; `.github/workflows/ci.yml` |
| README'deki her komut çalışıyor | ✅ | `python writer.py --help`, anahtarsız çalıştırma mesajı, `pytest`, `ruff check` elle koşuldu |

**Doğrulanmayan tek nokta:** gerçek Gemini API ile canlı uçtan uca koşu — bu ortamda API
anahtarı yok. Model çağrısının şekli değişmedi (aynı `generate_content`, aynı `Content`
akışı, aynı `thought_signature` koruması); değişen kısımlar sahte istemciyle kapsandı.
Anahtarınızla `python writer.py "5 bölümlük kısa bir hikâye yaz"` komutunu çalıştırmak
duman testi olarak yeterli olacaktır.

---

## Faz 1'e devreden borçlar

Değişmedi, planlandığı gibi Faz 1'de kapanacak: **B-03** (global proje klasörü),
**B-04** (okuma araçları yok), **B-05** (sıkıştırma araç çağrılarını düz metne indirger),
**B-08** (açık `finish_task` ile bitiş tespiti), **B-11** (gömülü yapılandırma),
**B-12** (`utils.py` sorumluluk karmaşası), **B-13** (`append` sessizce dosya yaratır).

Faz 1'e başlarken ilk adım `core/` paketini açıp `writer.py`'yi ince CLI katmanına
indirmek; bu fazda yazılan testler o yeniden yapılandırmanın güvenlik ağı.
