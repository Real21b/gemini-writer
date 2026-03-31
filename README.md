# Gemini Writer

A modern fullstack AI creative writing agent powered by **Google Gemini 3 Flash**. Create novels, books, and short story collections with an autonomous AI agent — via a sleek web UI **or** the classic CLI.

## ✨ Features

- 🤖 **Autonomous Writing** — The agent plans, reasons, and writes independently
- 🌐 **Modern Web UI** — React + Tailwind CSS dashboard with real-time streaming
- ⚡ **WebSocket Streaming** — Watch the agent think and write live
- 📚 **Multiple Formats** — Novels, books, short story collections
- 💾 **Smart Context Management** — Automatic compression near token limits
- 🔄 **Recovery Mode** — Resume interrupted work from saved summaries
- 📊 **Token Monitoring** — Real-time tracking with automatic optimization
- 🛠️ **Tool Use** — Agent creates projects, writes files, and manages its workspace
- 🧠 **Advanced Thinking** — Uses Gemini's HIGH thinking mode for better reasoning
- 🐳 **Docker Ready** — One-command deployment with Docker Compose
- 🗄️ **SQLite Database** — Project persistence via SQLAlchemy (async)
- 🧪 **Tested** — Backend API and tool tests with pytest

## 🏗️ Architecture

```
gemini-writer/
├── backend/                  # FastAPI backend
│   ├── main.py               # Application entry point
│   ├── models.py             # SQLAlchemy models
│   ├── schemas.py            # Pydantic schemas
│   ├── core/
│   │   ├── config.py         # Settings (from env)
│   │   └── database.py       # Async SQLite engine
│   ├── api/
│   │   ├── projects.py       # REST CRUD for projects
│   │   └── writer_ws.py      # WebSocket streaming endpoint
│   └── services/
│       └── writer_service.py # Core agentic loop (shared by CLI & API)
├── frontend/                 # React + Vite + Tailwind CSS
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components/       # Layout, shared UI
│   │   ├── hooks/            # useWebSocket
│   │   └── pages/            # Dashboard, NewProject, ProjectView
│   ├── package.json
│   └── vite.config.js
├── tools/                    # Agent tool implementations
│   ├── project.py            # Project folder management
│   ├── writer.py             # Markdown file writing
│   └── compression.py        # Context compression
├── tests/                    # pytest test suite
│   ├── test_api.py           # API endpoint tests
│   └── test_tools.py         # Tool unit tests
├── writer.py                 # CLI entry point (still works standalone)
├── utils.py                  # Shared utilities
├── pyproject.toml            # Modern Python packaging
├── requirements.txt          # Python dependencies
├── Dockerfile                # Multi-stage Docker build
├── docker-compose.yml        # One-command deployment
└── env.example               # Example environment config
```

## 🚀 Quick Start

### Prerequisites

- **Python 3.11+**
- **Node.js 18+** (for the frontend)
- A [Google Gemini API key](https://aistudio.google.com/app/apikey)

### 1. Install dependencies

```bash
# Backend
pip install -r requirements.txt

# Frontend
cd frontend && npm install && cd ..
```

### 2. Configure environment

```bash
cp env.example .env
# Edit .env and add your GEMINI_API_KEY
```

### 3a. Run the Web App (fullstack)

```bash
# Terminal 1 – Backend
uvicorn backend.main:app --reload

# Terminal 2 – Frontend
cd frontend && npm run dev
```

Open **http://localhost:5173** in your browser.

### 3b. Run the CLI (classic mode)

```bash
python writer.py "Create a collection of 5 sci-fi short stories about AI"

# Or interactively:
python writer.py
```

### 🐳 Docker

```bash
docker compose up --build
# → App available at http://localhost:8000
```

## 🌐 Web UI

| Page | Description |
|------|-------------|
| **Dashboard** | List all projects, see status & progress, delete projects |
| **New Project** | Create a project with name + prompt, or use quick templates |
| **Project View** | Real-time agent feed (thinking, content, tool calls), file browser with Markdown preview |

## 🔌 API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/projects` | List projects |
| `POST` | `/api/projects` | Create a project |
| `GET` | `/api/projects/:id` | Get project details |
| `DELETE` | `/api/projects/:id` | Delete a project |
| `GET` | `/api/projects/:id/files` | List project files |
| `GET` | `/api/projects/:id/files/:name` | Read a file |
| `WS` | `/ws/write/:id` | Start writing (WebSocket stream) |

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v
```

## ⚙️ Configuration

All settings can be overridden via environment variables (see `env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | *(required)* | Your Google Gemini API key |
| `MODEL_NAME` | `gemini-3-flash-preview` | Gemini model to use |
| `MAX_ITERATIONS` | `300` | Maximum agent iterations |
| `TOKEN_LIMIT` | `1000000` | Context window size |
| `COMPRESSION_THRESHOLD` | `900000` | Auto-compress at this token count |
| `DATABASE_URL` | `sqlite+aiosqlite:///./gemini_writer.db` | Database connection string |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Allowed CORS origins |

## 📖 How It Works

### The Agentic Loop

1. User submits a writing prompt (via web UI or CLI)
2. The agent receives the prompt and reasons using Gemini's HIGH thinking mode
3. It decides which tools to call (`create_project`, `write_file`, `compress_context`)
4. Tool results feed back into the conversation
5. The loop continues until the task is complete (up to 300 iterations)
6. Context is automatically compressed when approaching the 1M token limit

### Real-Time Streaming

The WebSocket endpoint (`/ws/write/:id`) pushes JSON events as the agent works:

```json
{"type": "thinking",    "data": {"text": "...", "iteration": 1}}
{"type": "content",     "data": {"text": "...", "iteration": 1}}
{"type": "tool_call",   "data": {"name": "write_file", "args": {...}}}
{"type": "tool_result", "data": {"name": "write_file", "result": "..."}}
{"type": "progress",    "data": {"iteration": 1, "tokens": 1234, ...}}
{"type": "done",        "data": {"message": "Completed in 42 iterations."}}
```

## 📄 License

MIT License with Attribution Requirement — see [LICENSE](LICENSE) file.

**Commercial Use**: If you use this software in a commercial product, you must provide clear attribution to Pietro Schirano (@Doriandarko).

## 🙏 Credits

- **Created by**: Pietro Schirano ([@Doriandarko](https://github.com/Doriandarko))
- **Powered by**: Google Gemini 3 Flash
- **Repository**: https://github.com/Doriandarko/gemini-writer
