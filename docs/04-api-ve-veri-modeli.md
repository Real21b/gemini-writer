# 4. API Sözleşmesi ve Veri Modeli

Bu bölüm Faz 2'nin uygulama planıdır. Sözleşme önce yazılır, backend ve frontend ona göre
paralel geliştirilir.

---

## 4.1 Veri modeli

```
users ──< projects ──< runs ──< events
                  └──< files ──< file_versions
```

### users (Faz 5'e kadar tek satır: "local")

| alan | tip | not |
|---|---|---|
| id | uuid | |
| email | text | |
| gemini_api_key_enc | text | BYOK, uygulama anahtarıyla şifreli |
| monthly_token_budget | bigint | 0 = sınırsız |

### projects

| alan | tip | not |
|---|---|---|
| id | uuid | |
| user_id | uuid | |
| title | text | kullanıcı düzenleyebilir |
| slug | text | dosya sistemi güvenli |
| kind | enum | `novel` / `collection` / `book` / `custom` |
| created_at / updated_at | timestamptz | |

### runs

| alan | tip | not |
|---|---|---|
| id | uuid | |
| project_id | uuid | |
| prompt | text | |
| status | enum | aşağıdaki durum makinesi |
| config | jsonb | model, temperature, thinking_level, max_iterations, token_budget |
| iteration | int | canlı ilerleme |
| tokens_prompt / tokens_output / tokens_thinking | bigint | |
| cost_estimate_usd | numeric(10,4) | |
| error | jsonb | tip, mesaj, tekrar denenebilir mi |
| started_at / finished_at | timestamptz | |

### events

| alan | tip | not |
|---|---|---|
| id | bigserial | |
| run_id | uuid | |
| seq | int | koşu içinde monoton; `(run_id, seq)` benzersiz |
| type | text | olay tablosu (bkz. 02-hedef-mimari §2.2) |
| data | jsonb | |
| ts | timestamptz | |

> `thinking.delta` / `text.delta` olayları çok sayıda ve kısa ömürlüdür. Öneri: bunları
> **50-200 ms'lik pencerelerde birleştirerek** yaz; ham parça akışını yalnızca canlı
> SSE'ye gönder. Aksi halde tek koşu yüz binlerce satır üretir.

### files / file_versions

| alan | tip | not |
|---|---|---|
| files.id | uuid | |
| files.project_id | uuid | |
| files.path | text | proje köküne göre |
| files.word_count | int | okuyucu ve ilerleme göstergesi için |
| file_versions.id | uuid | |
| file_versions.file_id | uuid | |
| file_versions.run_id | uuid | hangi koşu yazdı |
| file_versions.content_hash | text | |
| file_versions.storage_key | text | disk/S3 yolu |
| file_versions.created_at | timestamptz | |

---

## 4.2 Koşu durum makinesi

```
queued ──▶ running ──▶ completed
             │  ▲          
             │  └── resumed ◀── paused ◀── (kullanıcı duraklattı)
             │  └── answered ◀── needs_input ◀── (ajan ask_user çağırdı)
             ├──▶ failed        (kalıcı hata / ardışık hata eşiği)
             ├──▶ cancelled     (kullanıcı iptali)
             └──▶ interrupted   (sunucu yeniden başladı — devam ettirilebilir)
```

`interrupted` durumu `--recover` mantığının sunucu karşılığıdır: koşu, son bağlam anlık
görüntüsünden devam ettirilebilir olmalıdır.

---

## 4.3 REST uçları

### Koşular

```http
POST /api/runs
{
  "project_id": "uuid | null",        // null → yeni proje otomatik oluşturulur
  "prompt": "10 bölümlük Viktorya dönemi polisiye romanı yaz",
  "config": {
    "model": "gemini-3-flash-preview",
    "thinking_level": "HIGH",
    "temperature": 1.0,
    "max_iterations": 300,
    "token_budget": 2000000,
    "approval_mode": "auto" | "confirm_writes"
  }
}
→ 202 { "run_id": "...", "project_id": "...", "events_url": "/api/runs/{id}/events" }
```

| Uç | Yöntem | Açıklama |
|---|---|---|
| `/api/runs/{id}` | GET | Durum, ilerleme, kullanım, hata |
| `/api/runs/{id}/cancel` | POST | Nazik iptal; mevcut tur biter, bağlam anlık görüntüsü alınır |
| `/api/runs/{id}/pause` · `/resume` | POST | Duraklat / devam et |
| `/api/runs/{id}/steer` | POST | `{ "message": "3. bölüm daha karanlık olsun" }` — bir sonraki tura enjekte edilir |
| `/api/runs/{id}/answer` | POST | `needs_input` durumundaki soruya cevap |
| `/api/runs/{id}/approve` | POST | `confirm_writes` modunda bekleyen yazmayı onayla/reddet |
| `/api/runs/{id}/resume-from-snapshot` | POST | `interrupted` koşuyu devam ettir |

### Projeler ve dosyalar

| Uç | Yöntem | Açıklama |
|---|---|---|
| `/api/projects` | GET / POST | Liste (sayfalı) / oluştur |
| `/api/projects/{id}` | GET / PATCH / DELETE | Başlık düzenleme dahil |
| `/api/projects/{id}/files` | GET | Ağaç + kelime sayısı + son güncelleme |
| `/api/files/{id}` | GET / PUT | İçerik oku / kullanıcı düzenlemesini kaydet (yeni sürüm) |
| `/api/files/{id}/versions` | GET | Sürüm listesi |
| `/api/files/{id}/versions/{vid}/restore` | POST | Geri alma |
| `/api/projects/{id}/export?format=md\|zip\|pdf\|epub` | POST | Asenkron; iş kimliği döner |

---

## 4.4 SSE sözleşmesi

```http
GET /api/runs/{id}/events
Accept: text/event-stream
Last-Event-ID: 412           # opsiyonel — bu sıradan sonrası gönderilir
```

```
id: 413
event: thinking.delta
data: {"text":"Bölüm yapısını planlıyorum..."}

id: 414
event: file.written
data: {"path":"chapter_03.md","bytes":18422,"words":3104,"mode":"create"}

id: 415
event: usage.updated
data: {"total":184320,"cost_estimate_usd":0.42}

: ping
```

Kurallar:

1. **Her olayın `id`'si `seq`'tir.** İstemci yeniden bağlandığında `Last-Event-ID` gönderir;
   sunucu DB'den eksik olayları oynatır, sonra canlı akışa geçer.
2. **15 saniyede bir `: ping`** yorumu — ara sunucuların bağlantıyı kesmesini engeller.
3. **Akış bittiğinde** `run.completed` / `run.failed` / `run.cancelled` olayı gönderilir ve
   bağlantı kapatılır; istemci yeniden bağlanmaya çalışmaz.
4. Tamamlanmış koşuda uç, tüm olay geçmişini oynatıp kapanır — "kayıttan izleme" bedava gelir.

---

## 4.5 Hata biçimi

Tüm hatalar tek biçim döner:

```json
{
  "error": {
    "type": "rate_limited | invalid_api_key | budget_exceeded | not_found | validation_error | internal",
    "message": "Kullanıcıya gösterilebilir açıklama",
    "retryable": true,
    "retry_after_seconds": 30
  }
}
```

Frontend `type` alanına göre davranır: `invalid_api_key` → ayarlar sayfasına yönlendir,
`budget_exceeded` → bütçe kartını aç, `rate_limited` → geri sayımlı yeniden dene düğmesi.

---

## 4.6 Tip üretimi

Backend Pydantic modelleri → OpenAPI → `openapi-typescript` ile frontend tipleri.
Olay yükleri de Pydantic modeli olarak tanımlanır ve OpenAPI şemasına
`components/schemas/Event*` olarak eklenir; böylece SSE yükleri de tipli olur.
Elle yazılmış TypeScript arayüzü bulundurmayın — kayma kaçınılmazdır.
