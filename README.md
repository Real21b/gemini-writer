# Gemini Writing Agent

An autonomous agent powered by **Google's Gemini 3 Flash** model for creating novels, books, and short story collections.

## Features

- 🤖 **Autonomous Writing**: The agent plans and executes creative writing tasks independently
- 📚 **Multiple Formats**: Create novels, books, or short story collections
- 💾 **Smart Context Management**: Automatically compresses context when approaching token limits
- 🔄 **Recovery Mode**: Resume interrupted work from saved context summaries
- ⚡ **Real-Time Streaming**: thinking and prose appear as the model produces them
- 🧠 **Long-Term Memory**: a story bible plus read-back tools keep a 100k-word manuscript consistent
- 📊 **Token Monitoring**: per-iteration token usage read straight from the API response
- 🛠️ **Tool Use**: Agent can create projects, write files, and manage its workspace
- 🧠 **Advanced Thinking**: Uses Gemini's thinking mode for better reasoning
- 🔁 **Resilient**: Transient API errors are retried with exponential backoff; permanent ones stop the run cleanly

> Streaming is on by default; pass `--no-stream` to print each turn only once it is complete.

## Development Guide

A layered development guide (in Turkish) covering the current code audit, target
fullstack architecture, phased roadmap, API contract and UX design lives in
[`docs/`](docs/00-genel-bakis.md).

## Installation

### Prerequisites

We recommend using [uv](https://github.com/astral-sh/uv) for fast Python package management:

```bash
# Install uv (if you don't have it)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Setup

1. Install dependencies:

**Using uv (recommended):**
```bash
uv pip install -r requirements.txt
```

**Or using pip:**
```bash
pip install -r requirements.txt
```

2. Configure your API key:

Create a `.env` file with your API key:
```bash
# Copy the example file
cp env.example .env

# Edit .env and add your API key
# The file should contain:
GEMINI_API_KEY=your-api-key-here
```

Get your Gemini API key from: https://aistudio.google.com/app/apikey

## Usage

### Fresh Start

Run with an inline prompt:
```bash
# Using uv (recommended)
uv run writer.py "Create a collection of 5 sci-fi short stories about AI"

# Or using python directly
python writer.py "Create a collection of 5 sci-fi short stories about AI"
```

Or run interactively:
```bash
uv run writer.py
# or: python writer.py
```
Then enter your prompt when asked.

### Recovery Mode

If the agent is interrupted or you want to continue previous work:
```bash
uv run writer.py --recover output/my_project/.context_summary_20250107_143022.md
# or: python writer.py --recover output/my_project/.context_summary_20250107_143022.md
```

## How It Works

### The Agent's Tools

| Tool | What it does |
|------|--------------|
| `create_project` | Creates the project folder (always called first) |
| `write_file` | Writes a file — modes `create`, `append`, `overwrite` |
| `read_file` | Reads back what was already written (optionally just the tail) |
| `list_files` | Lists every file with its word count |
| `apply_patch` | Replaces one exact passage — cheaper than rewriting a chapter |
| `read_story_bible` / `update_story_bible` | The agent's long-term memory: characters, places, timeline |
| `finish_task` | The only way to end a run |
| `ask_user` | Pauses the run when a decision truly needs you |

### The Agentic Loop

1. The agent receives your prompt
2. It plans the structure into `00_plan.md` and seeds `story_bible.md`
3. For each chapter it re-reads the bible, checks how the previous chapter ended,
   writes the chapter in full, then records the new facts
4. It continues until every planned piece exists, then calls `finish_task`
5. A turn that returns text without a tool call does **not** end the run — the agent is
   nudged to continue, and after repeated silence the run pauses for your input

### Context Management

- **Token Limit**: 1,000,000 tokens (Gemini's context window)
- **Auto-Compression**: triggers at 65% of the limit — older turns are summarized while
  recent turns stay intact, and the cut always lands on a turn boundary so a tool call is
  never separated from its result
- **Durable core**: after every compression the context still carries the original request,
  the story bible and the list of files on disk
- **Backups**: recovery snapshots every 25 iterations, on Ctrl+C, and on failure
- **Recovery**: `--recover <snapshot>` resumes the work

## Project Structure

```
gemini-writer/
├── writer.py             # Entry point
├── core/                 # The agent — no CLI, no HTTP, no globals
│   ├── config.py         # Settings (env) + RunConfig (per run)
│   ├── events.py         # The event stream every interface consumes
│   ├── workspace.py      # The only code that touches the filesystem
│   ├── llm.py            # Gemini wrapper: streaming, retries, usage
│   ├── context.py        # Compression, turn boundaries, snapshots
│   ├── runner.py         # The agent loop (yields events, never prints)
│   ├── prompts.py        # System and summarization prompts
│   └── tools/            # Tool registry; schemas derived from Pydantic models
├── cli/                  # Thin client: argument parsing + console renderer
├── tests/                # Test suite (no API key required)
├── docs/                 # Development guide and roadmap
├── pyproject.toml        # Dependencies, lint and test configuration
├── requirements.txt      # Python dependencies
├── env.example           # Example configuration
├── .gitignore            # Git ignore rules
└── README.md             # This file

# Generated during use:
output/                   # All AI-generated projects go here
├── your_project_name/    # Created by the agent
│   ├── chapter_01.md     # Written by the agent
│   ├── chapter_02.md
│   └── .context_summary_*.md  # Auto-saved context summaries
└── another_project/
    └── ...
```

## Examples

### Example 1: Novel
```bash
uv run writer.py "Write a mystery novel set in Victorian London with 10 chapters"
```

### Example 2: Short Story Collection
```bash
uv run writer.py "Create 7 interconnected sci-fi short stories exploring the theme of memory"
```

### Example 3: Book
```bash
uv run writer.py "Write a comprehensive guide to Python programming with 15 chapters"
```

## Advanced Features

### Visible Reasoning
The agent streams as it works:
- 🧠 **Thinking**: the model's reasoning, token by token (Gemini's thinking mode)
- 💬 **Response**: prose as it is written
- 🔧 **Tool Calls**: which tools ran, with their arguments and results
- 📄 **Files**: every file as it lands, with its word count

### Iteration Counter
The agent displays its progress: `Iteration X/300`

### Token Monitoring
Token usage after every call, shown with `--verbose`. The count comes from the API response
itself, so tracking costs no extra requests.

### Useful Flags
`--model`, `--max-iterations`, `--temperature`, `--thinking {LOW,MEDIUM,HIGH}`,
`--output-dir`, `--no-stream`, `--verbose`.

Exit codes: `0` completed (or interrupted with a snapshot saved), `1` failed,
`2` the agent needs your input.

### Error Handling
Transient failures (429, 503, timeouts) are retried up to 5 times with exponential
backoff and jitter. Permanent failures (invalid API key, malformed request) stop the run
immediately and save a recovery snapshot. After 5 consecutive failed iterations the run
stops instead of burning through the iteration budget.

### Graceful Interruption
Press `Ctrl+C` to interrupt. The agent will save the current context for recovery.

## Tips for Best Results

1. **Be Specific**: Clear prompts get better results
   - Good: "Create a 5-chapter romance novel set in modern Tokyo"
   - Less good: "Write something interesting"

2. **Let It Work**: The agent works autonomously - it will plan and execute the full task

3. **Recovery is Easy**: If interrupted, just use the `--recover` flag with the latest context summary

4. **Check Progress**: Generated files appear in real-time in the project folder

## Troubleshooting

### "GEMINI_API_KEY environment variable not set"
Make sure you have created a `.env` file in the project root with your API key:
```bash
GEMINI_API_KEY=your-actual-api-key-here
```

### "401 Unauthorized" or Authentication errors
- Verify your API key is correct in the `.env` file
- Get your API key from: https://aistudio.google.com/app/apikey

### "Error creating project folder"
Check write permissions in the current directory

### Agent seems stuck
The agent can run up to 300 iterations. For very complex tasks, this is normal. Check the project folder to see progress.

### Token limit issues
The agent automatically compresses context at 900K tokens. If you see compression messages, the system is working correctly.

## Technical Details

- **Model**: gemini-3-flash-preview
- **Thinking Level**: HIGH (for better reasoning)
- **Temperature**: 1.0
- **Context Window**: 1,000,000 tokens
- **Max Iterations**: 300
- **Compression Threshold**: 65% of the token limit
- **Write Sandbox**: the agent can only write `.md`, `.txt`, `.json` and `.yaml` files
  inside the active project folder (max 5 MB per file, 5 directory levels deep)

You can customize these settings in `writer.py`.

## Development

```bash
# Install with dev dependencies
uv pip install -e ".[dev]"

# Lint and test (no API key needed - the suite uses a fake client)
ruff check .
pytest
```

The full development guide, code audit and fullstack roadmap live in
[`docs/`](docs/00-genel-bakis.md).

## License

MIT License with Attribution Requirement - see [LICENSE](LICENSE) file for details.

**Commercial Use**: If you use this software in a commercial product, you must provide clear attribution to Pietro Schirano (@Doriandarko).

**API Usage**: This project uses the Google Gemini API. Please refer to Google's terms of service for API usage guidelines.

## Credits

- **Created by**: Pietro Schirano ([@Doriandarko](https://github.com/Doriandarko))
- **Powered by**: Google's Gemini 3 Flash model
- **Repository**: https://github.com/Doriandarko/gemini-writer


