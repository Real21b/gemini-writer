# 2. Hedef Mimari

Hedef: **çekirdek ajan** (arayüzden bağımsız) + **API katmanı** + **web arayüzü**.
CLI ortadan kalkmaz; çekirdeğin en ince istemcisi olarak kalır ve regresyon testi görevi
görür.

```
┌───────────────┐   ┌───────────────┐   ┌───────────────────────┐
│  Web (Next.js)│   │  CLI (writer) │   │ Otomasyon / Webhook   │
└───────┬───────┘   └───────┬───────┘   └───────────┬───────────┘
        │ REST + SSE        │ doğrudan çağrı        │
        ▼                   │                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                    API (FastAPI)                                │
│   /runs  /projects  /files  /events(SSE)  /exports  /auth       │
└───────┬─────────────────────────────────────────────┬───────────┘
        │                                             │
        ▼                                             ▼
┌───────────────────────┐                   ┌──────────────────────┐
│  İş yürütücü (worker) │──── olaylar ────▶ │ Olay deposu + DB     │
│  AgentRunner          │                   │ Postgres / SQLite    │
└───────┬───────────────┘                   └──────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  core/  — Gemini istemcisi · araçlar · bağlam yöneticisi ·      │
│           Workspace (dosya sistemi sınırı) · olay üreteci       │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2.1 Çekirdek (`core/`) paketi

```
core/
├── config.py        Settings (env) + RunConfig (koşu bazlı)
├── events.py        Olay tipleri ve olay veri yolu (event bus)
├── workspace.py     Workspace: kök dizin, güvenli yol çözümü, dosya G/Ç
├── context.py       ContextManager: token muhasebesi, sıkıştırma, anlık görüntü
├── llm.py           Gemini sarmalayıcı: akış, yeniden deneme, kullanım metrikleri
├── runner.py        AgentRunner: ajan döngüsü (tek sınıf, global durum yok)
├── prompts/         Sistem promptları ve şablonlar (metin dosyaları)
└── tools/
    ├── base.py      @tool dekoratörü, Pydantic tabanlı şema üretimi, registry
    ├── project.py   create_project
    ├── files.py     write_file, read_file, list_files, apply_patch
    ├── bible.py     update_story_bible, read_story_bible
    └── control.py   finish_task, ask_user
```

### Workspace — dosya sistemi sınırı

Global değişkenin (B-03) yerini alan sözleşme. Dosya sistemine dokunan **tek** yer burası.

```python
# core/workspace.py
from pathlib import Path
from dataclasses import dataclass

ALLOWED_SUFFIXES = {".md", ".txt", ".json", ".yaml"}
MAX_FILE_BYTES = 2_000_000

@dataclass(frozen=True)
class Workspace:
    root: Path          # ör. /data/projects/<run_id>

    def resolve(self, filename: str) -> Path:
        if not filename or filename.startswith("."):
            raise ValueError("Geçersiz dosya adı")
        path = (self.root / filename).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("Çalışma alanı dışına yazma engellendi")
        if path.suffix not in ALLOWED_SUFFIXES:
            raise ValueError(f"İzin verilmeyen uzantı: {path.suffix}")
        return path

    def write(self, filename: str, content: str, mode: str) -> int:
        path = self.resolve(filename)
        if mode == "create" and path.exists():
            raise FileExistsError(filename)
        if mode == "append" and not path.exists():
            raise FileNotFoundError(filename)     # B-13
        if len(content.encode()) > MAX_FILE_BYTES:
            raise ValueError("Dosya boyutu sınırı aşıldı")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8") if mode != "append" \
            else path.open("a", encoding="utf-8").write(content)
        return len(content)
```

Her koşu kendi `Workspace`'ini alır; araçlar `Workspace`'i parametre olarak enjekte
edilmiş şekilde çağrılır. Böylece aynı süreçte 50 koşu paralel çalışabilir.

### Araç kaydı — şema tek kaynaktan üretilir

B-12'ye çözüm: imza ile şemayı ayrı ayrı yazmayı bırakın.

```python
# core/tools/base.py
from pydantic import BaseModel
from typing import Callable, Type

REGISTRY: dict[str, "ToolSpec"] = {}

class ToolSpec(BaseModel):
    name: str
    description: str
    args_model: Type[BaseModel]
    fn: Callable
    needs_workspace: bool = True

def tool(name: str, description: str, args: Type[BaseModel], **kw):
    def deco(fn):
        REGISTRY[name] = ToolSpec(name=name, description=description,
                                  args_model=args, fn=fn, **kw)
        return fn
    return deco
```

`args_model.model_json_schema()` → Gemini `FunctionDeclaration` şemasına dönüştürülür.
Bir alan eklendiğinde şema kendiliğinden güncellenir; kayma imkânsız hale gelir.

### Genişletilmiş araç seti

| Araç | Amaç | Faz |
|---|---|---|
| `create_project` | Çalışma alanını hazırlar | var |
| `write_file` | Dosya yazar (create/append/overwrite) | var |
| `read_file` | **Yazdığını geri okur** — süreklilik için kritik | 1 |
| `list_files` | Dosya envanteri + boyut/kelime sayısı | 1 |
| `apply_patch` | Tüm dosyayı yeniden yazmadan hedefli düzeltme (token tasarrufu) | 1 |
| `update_story_bible` | Karakter/mekân/zaman çizgisi kaydı | 1 |
| `read_story_bible` | Bölüm yazmadan önce zorunlu okuma | 1 |
| `finish_task` | Görevi açıkça bitirir (B-08) | 1 |
| `ask_user` | Belirsizlikte kullanıcıya sorar, koşuyu `needs_input` yapar | 4 |

`compress_context` **araç olmaktan çıkarılır**; bağlam yönetimi sistemin işidir, modelin
değil (zaten prompt'ta "bunu çağırma" deniyor — o zaman araç olarak sunulmamalı).

---

## 2.2 Olay protokolü

Ajan döngüsü artık `print` etmez; **olay üretir**. CLI olayları terminale basar, API
SSE'ye yazar, veritabanı olayları saklar. Kurtarma = olayları yeniden oynatma.

```python
# core/events.py
class Event(BaseModel):
    run_id: str
    seq: int                 # monoton artan; SSE Last-Event-ID ile devam için
    ts: datetime
    type: EventType
    data: dict
```

| Olay | Ne zaman | Yük (data) |
|---|---|---|
| `run.started` | koşu başında | prompt, model, config |
| `iteration.started` | her tur | iteration, max_iterations |
| `thinking.delta` | düşünme akışı | text |
| `text.delta` | yanıt akışı | text |
| `tool.call` | araç çağrısı | name, args |
| `tool.result` | araç sonucu | name, ok, result, duration_ms |
| `file.written` | dosya yazıldı | path, bytes, words, mode |
| `usage.updated` | token güncellemesi | prompt, output, thinking, total, cost_estimate |
| `context.compressed` | sıkıştırma | before, after, summary_path |
| `run.needs_input` | ajan soru sordu | question |
| `run.paused` / `run.resumed` | kullanıcı müdahalesi | reason |
| `run.completed` | bitiş | summary, files |
| `run.failed` | hata | error_type, message, retryable |

Bu tablo hem backend hem frontend için tek sözleşmedir; yeni bir olay eklemek arayüzde
yeni bir kutu demektir, mimari değişiklik değil.

---

## 2.3 Akış (streaming) — README'nin vaadini gerçekten karşılamak

B-10'da görüldüğü gibi bugün akış yok. Çözüm `generate_content_stream` + parça
birleştirme. Kritik nokta: **akış sırasında `thought_signature` ve `function_call`
parçaları kaybolmamalı**; parçalar biriktirilip tam `Content` yeniden kurulmalı.

```python
# core/llm.py (özet)
async def stream_turn(self, contents, config) -> AsyncIterator[Event]:
    parts_acc, usage = [], None
    async for chunk in self.client.aio.models.generate_content_stream(
            model=config.model, contents=contents, config=config.to_genai()):
        for part in chunk.candidates[0].content.parts:
            if getattr(part, "thought", False) and part.text:
                yield Event(type="thinking.delta", data={"text": part.text})
            elif part.function_call:
                yield Event(type="tool.call", data={"name": part.function_call.name})
            elif part.text:
                yield Event(type="text.delta", data={"text": part.text})
            parts_acc.append(part)          # ham parça korunur
        usage = chunk.usage_metadata or usage
    self.last_content = types.Content(role="model", parts=parts_acc)
    self.last_usage = usage                 # B-07: ayrı count_tokens'a gerek yok
```

---

## 2.4 Bağlam yönetimi (yeniden tasarım)

Bugünkü yaklaşım "900K'ya gelince her şeyi düz metne çevir" (B-05). Yeni yaklaşım katmanlı:

1. **Kalıcı çekirdek (her zaman bağlamda):** sistem promptu + `story_bible.md` özeti +
   taslak planı + dosya envanteri. Yaklaşık 5-10K token, asla silinmez.
2. **Sıcak pencere:** son N tam tur, **ham `Content` olarak** (imzalar korunur).
3. **Soğuk arşiv:** özetlenip tek bir mesaja indirgenir; tam metin diskte, ajan gerekirse
   `read_file` ile geri getirir.

Eşik %90 yerine **%60-70**'e çekilmeli: 900K token'lık bir istek hem yavaş hem pahalıdır
hem de kalite modelin dikkat dağılımı nedeniyle düşer. Uzun metin ajanlarında "bağlamı
tıka basa doldur" stratejisi, "diskte tut, ihtiyaç oldukça oku" stratejisine yenilir.

**Kesme kuralı:** kesme noktası daima tur sınırında olmalı; `function_call` içeren model
mesajı ile karşılığındaki `function_response` asla ayrılmamalı.

---

## 2.5 API katmanı (FastAPI)

- Neden FastAPI: çekirdek zaten Python; async yerli; Pydantic modelleri hem doğrulama hem
  OpenAPI şeması veriyor (frontend tipleri buradan üretilir).
- **SSE, WebSocket'e tercih edilir**: akış tek yönlü, HTTP altyapısıyla uyumlu, `Last-Event-ID`
  ile yeniden bağlanma yerleşik. Kontrol komutları (durdur, yönlendir) ayrı POST uçlarıyla
  gider — çift yönlü sokete gerek yok.
- **İş yürütme:** Faz 2'de `asyncio.Task` + süreç içi kayıt yeterli. Çok kullanıcıya
  geçerken (Faz 5) ayrı worker süreci + Redis/RQ. Kod farkı küçük tutulmalı: runner zaten
  arayüzden bağımsız.

Sözleşmenin tamamı: [04-api-ve-veri-modeli.md](04-api-ve-veri-modeli.md).

---

## 2.6 Frontend yığını

| Katman | Seçim | Gerekçe |
|---|---|---|
| Çatı | Next.js (App Router) + TypeScript | SSR + dosya bazlı yönlendirme, tek dağıtım |
| Stil | Tailwind + shadcn/ui | Hızlı, tutarlı, erişilebilir temel bileşenler |
| Sunucu durumu | TanStack Query | Önbellek, yeniden çekme, iyimser güncelleme |
| Canlı durum | `EventSource` + Zustand | SSE olayları tek store'da toplanır |
| Editör | CodeMirror 6 (markdown) | Uzun metinde sanal kaydırma, hafif |
| Dışa aktarma | `markdown-it` → HTML/PDF, `epub-gen` | Kullanıcı ürünü elle taşımamalı |

Tasarım detayı: [05-frontend-ux.md](05-frontend-ux.md).

---

## 2.7 Depolama

- **Metadata (Postgres/SQLite):** kullanıcı, proje, koşu, olay, dosya kaydı, kullanım.
- **İçerik (dosya sistemi/S3):** `.md` dosyaları. Veritabanına gömmeyin: dışa aktarma,
  yedekleme ve git benzeri sürümleme dosya sisteminde çok daha ucuz.
- **Sürüm geçmişi:** her `write_file` sonrası içerik özeti (hash) + önceki sürüm kopyası.
  Kullanıcı "ajan 3. bölümü bozdu" dediğinde geri alma tek tık olmalı.

---

## 2.8 Hedef depo yapısı

```
gemini-writer/
├── core/                  # ajan çekirdeği (arayüzsüz)
├── cli/                   # writer.py'nin devamı — çekirdeğin ince istemcisi
├── api/                   # FastAPI uygulaması
│   ├── main.py  routers/  schemas/  db/  workers/
├── web/                   # Next.js uygulaması
├── tests/                 # unit + entegrasyon (sahte LLM ile)
├── docs/                  # bu rehber
├── docker/                # Dockerfile'lar + compose
├── pyproject.toml         # bağımlılıklar + ruff + pytest yapılandırması
└── .env.example
```
