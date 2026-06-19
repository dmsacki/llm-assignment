# University Student Support Assistant

A self-hosted LLM application that answers student questions about course
registration, examination rules, library services, ICT support, hostel
applications, fee payment, the academic calendar, and student conduct.

Built for **IS 365 — Practical Assignment: Full-Stack Pipeline for Deploying
a Self-Hosted LLM Application**.

The system runs entirely on local infrastructure: a local LLM served by
**Ollama**, a **FastAPI** backend, and a **Streamlit** frontend — no external
API keys or cloud LLM services required.

---

## 1. Project Structure

```
student-support-llm/
├── backend/
│   ├── __init__.py
│   ├── main.py            # FastAPI app: /health, /ask, /feedback routes
│   ├── llm_client.py       # Talks to Ollama; prompt design; error handling
│   ├── config.py           # Centralized settings (reads from .env)
│   ├── logging_config.py   # Rotating file + console logger setup
│   └── logs/
│       ├── app.log          # Created automatically at runtime
│       └── feedback.jsonl   # Created automatically when feedback is given
├── frontend/
│   └── app.py              # Streamlit chat UI
├── tests/
│   └── test_api.py         # pytest suite for the backend API
├── docs/
│   ├── report.md           # Technical report (Sections 1-10)
│   ├── reflection.md        # Answers to all Task 9 reflection questions
│   └── screenshots/         # Place your evidence screenshots here
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

| Folder/File | Purpose |
|---|---|
| `backend/` | All server-side code: API, LLM client, config, logging |
| `frontend/` | The Streamlit user interface |
| `tests/` | Automated API tests (pytest) |
| `docs/` | Report, reflection, and screenshot evidence for submission |
| `requirements.txt` | All Python dependencies |
| `.env.example` | Template for environment configuration |

---

## 2. Prerequisites

- Python 3.10 or above
- [Ollama](https://ollama.com) installed for your OS (Windows, macOS, or Linux)
- ~2 GB free disk space for the local model

---

## 3. Installation Guide

### Step 1 — Clone or extract the project

```bash
cd student-support-llm
```

### Step 2 — Create and activate a virtual environment

**Windows (PowerShell):**
```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

You should see `(venv)` appear at the start of your terminal prompt.

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4 — Install and start Ollama

Download and install Ollama from https://ollama.com for your operating
system, then start the Ollama server (if it isn't already running as a
background service):

```bash
ollama serve
```

### Step 5 — Pull the lightweight model

In a separate terminal:

```bash
ollama pull llama3.2:1b
```

You can swap in `phi3` or any other lightweight model — just update
`OLLAMA_MODEL` in your `.env` file to match.

### Step 6 — Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and adjust values if needed (defaults work out of the box for a
local setup).

---

## 4. Running the Application

Run each component in its own terminal (with the virtual environment
activated in each).

### Terminal 1 — Start the FastAPI backend

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

- API root: http://localhost:8000
- Interactive Swagger docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

### Terminal 2 — Start the Streamlit frontend

```bash
streamlit run frontend/app.py
```

This opens the chat UI in your browser, typically at http://localhost:8501.

### Terminal 3 — Run the automated tests

```bash
pytest tests/test_api.py -v
```

---

## 5. API Documentation

### `GET /health`
Returns whether the API and the local LLM are reachable.

**Response 200:**
```json
{
  "api_status": "ok",
  "ollama_reachable": true,
  "model": "llama3.2:1b"
}
```

### `POST /ask`
Send a student question and receive an answer.

**Request:**
```json
{ "question": "How do I register for courses this semester?" }
```

**Response 200:**
```json
{
  "question": "How do I register for courses this semester?",
  "answer": "You can register through the student portal during the official registration window...",
  "model": "llama3.2:1b",
  "latency_ms": 842,
  "timestamp": "2026-06-19T10:15:32.123456+00:00"
}
```

**Error responses:**

| Status | Meaning |
|---|---|
| 422 | Empty, missing, or too-long question |
| 503 | Ollama / model server is not running |
| 504 | Model took too long to respond |
| 502 | Model returned an invalid/unreadable response |
| 500 | Unexpected server error |

### `POST /feedback`
Rate a given answer (bonus feature — Task 10, Option E).

**Request:**
```json
{
  "question": "How do I register for courses?",
  "answer": "You can register through the student portal...",
  "rating": "Good"
}
```

**Response 200:**
```json
{ "status": "saved" }
```

Feedback is appended to `backend/logs/feedback.jsonl`, one JSON object per line.

---

## 6. Logging

All questions, answers, errors, and timestamps are written to
`backend/logs/app.log` (rotating at 1 MB, keeping 3 backups). View it live with:

```bash
tail -f backend/logs/app.log
```

---

## 7. Configuration Reference (`.env`)

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server address |
| `OLLAMA_MODEL` | `llama3.2:1b` | Model name to use |
| `REQUEST_TIMEOUT_SECONDS` | `30` | Max time to wait for the LLM |
| `MAX_QUESTION_LENGTH` | `500` | Max characters allowed per question |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `LOG_FILE_PATH` | `backend/logs/app.log` | Log file location |
| `FEEDBACK_FILE_PATH` | `backend/logs/feedback.jsonl` | Feedback file location |
| `API_HOST` / `API_PORT` | `0.0.0.0` / `8000` | Backend bind address |
| `BACKEND_URL` | `http://localhost:8000` | URL the frontend uses to reach the backend |

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Frontend shows "Connection error" | Backend not running | Start the `uvicorn` command above |
| Backend returns 503 on `/ask` | Ollama not running or model not pulled | Run `ollama serve` and `ollama pull llama3.2:1b` |
| Very slow first response | Model loading into memory for the first time | Wait; subsequent requests are faster |
| `ModuleNotFoundError: backend` | Commands run from the wrong directory | Always run `uvicorn`/`pytest` from the project root |

---

## 9. Project Documentation

- Technical report: [`docs/report.md`](docs/report.md)
- Reflection answers: [`docs/reflection.md`](docs/reflection.md)
- Screenshot evidence: [`docs/screenshots/`](docs/screenshots/)
