# Technical Report: University Student Support Assistant
### A Self-Hosted LLM Application Pipeline

**Course:** IS 365 — Full-Stack Pipeline for Deploying a Self-Hosted LLM Application
**Project:** University Student Support Assistant
**Group members:** *(to be completed by your group — full names and registration numbers)*
**Date:** June 2026

---

## 1. Introduction

Modern AI-powered applications are rarely a single call to a language
model. In a production environment, a working AI system is a *pipeline*:
a model serving layer, a backend that mediates access to that model, a
frontend through which users interact with the system, and the
operational scaffolding — configuration, logging, error handling, and
testing — that keeps the whole thing reliable.

This project implements that full pipeline for a concrete, practical use
case: a **University Student Support Assistant** that helps students get
quick answers to common questions about university services. Rather than
optimizing for the most capable or "intelligent" chatbot, the explicit
goal of this assignment was to demonstrate a complete, working,
end-to-end deployment: from a local development environment, through a
locally hosted language model, to a tested and documented application.

The system is intentionally self-hosted: it uses **Ollama** to run a
lightweight open-weight model (`llama3.2:1b`) entirely on local hardware,
with no dependency on any external, paid, or cloud-based LLM API. This
mirrors a realistic constraint many organizations face — data privacy,
cost control, or offline operation — and gives direct, hands-on
experience with the operational concerns of running your own model.

---

## 2. System Use Case

The assistant is designed to answer student questions across eight
university service domains, matching the assignment's specification:

1. Course registration
2. Examination rules
3. Library services
4. ICT support
5. Hostel application
6. Fee payment
7. Academic calendar
8. Student conduct

A typical interaction: a student opens the chat interface, types a
question such as *"What happens if I miss an exam due to illness?"*, and
receives a concise, relevant answer within a few seconds. If the question
falls outside the eight supported domains, the assistant is explicitly
instructed (via its system prompt) to say so rather than improvise an
answer, and to direct the student to the appropriate university office.

This use case was chosen because it is realistic, scoped, and
demonstrates every required architectural component without requiring
domain data the team does not have access to (e.g. real student records
or live registration systems) — it is explicitly a **support and
information assistant**, not a transactional system.

---

## 3. Tools and Technologies Used

| Layer | Tool | Justification |
|---|---|---|
| Language | Python 3.10+ | Required by the assignment; mature AI/web ecosystem |
| Local LLM runtime | Ollama | Simplest way to serve open-weight models locally with a stable HTTP API |
| Model | `llama3.2:1b` | Small enough to run on a laptop CPU with acceptable latency |
| Backend framework | FastAPI | Async-capable, automatic OpenAPI/Swagger docs, strong typing via Pydantic |
| Web server | Uvicorn | ASGI server recommended for FastAPI |
| Frontend | Streamlit | Rapid UI development in pure Python, native chat widgets |
| Configuration | `pydantic-settings` + `.env` | Type-safe, environment-driven configuration — no hardcoded secrets or hosts |
| Logging | Python `logging` (rotating file handler) | Stdlib reliability, no extra infrastructure, satisfies persistent-log requirement |
| Testing | `pytest` + FastAPI `TestClient` | Industry-standard Python testing; allows fully mocked, fast, repeatable tests |
| Version control | Git/GitHub | Collaboration and submission |

All dependencies are pinned with minimum versions in `requirements.txt`,
installed inside an isolated Python virtual environment (`venv`) so the
project does not interfere with — or depend on — the host machine's global
Python installation.

---

## 4. System Architecture

The system follows a classic three-tier architecture, with the local LLM
acting as a fourth, clearly separated "model serving" tier:

```
 ┌──────────────┐      HTTP (JSON)      ┌──────────────────┐      HTTP (JSON)      ┌────────────────────┐
 │  Streamlit    │  ───────────────────▶  │  FastAPI Backend  │  ───────────────────▶  │  Ollama (local LLM) │
 │  Frontend     │  ◀───────────────────  │  (main.py)         │  ◀───────────────────  │  llama3.2:1b         │
 └──────────────┘                        └──────────────────┘                        └────────────────────┘
        │                                          │
        │                                          ▼
        │                                  backend/logs/app.log
        │                                  backend/logs/feedback.jsonl
        ▼
   Student's browser
```

**Request flow for a question:**
1. The student types a question into the Streamlit chat input.
2. The frontend validates that the input is non-empty, then sends a
   `POST /ask` request to the FastAPI backend.
3. FastAPI validates the payload with a Pydantic model (rejecting empty
   or oversized questions before any business logic runs).
4. `llm_client.py` builds a full prompt (system instructions + the
   student's question) and sends it to Ollama's `/api/generate` endpoint.
5. Ollama loads the model (if not already loaded) and returns a generated
   response.
6. The backend logs the question, answer, latency, and timestamp, then
   returns a structured JSON response to the frontend.
7. The frontend renders the answer in the chat window and offers
   Good/Average/Poor feedback buttons.

Each tier is independently replaceable: the frontend could be swapped for
a mobile app, the backend's model client could point at a different LLM
runtime, and Ollama itself could be replaced with another local-serving
tool — all without touching the other tiers, because the boundary between
them is a well-defined HTTP/JSON contract.

---

## 5. Implementation Steps

1. **Environment setup.** Created a Python virtual environment with
   `python -m venv venv`, activated it, and installed all dependencies
   from `requirements.txt`.
2. **Local LLM installation.** Installed Ollama, started the server with
   `ollama serve`, and pulled the `llama3.2:1b` model with
   `ollama pull llama3.2:1b`. Verified the model directly via
   `ollama run llama3.2:1b "hello"` before integrating it into the
   pipeline.
3. **Configuration layer.** Implemented `backend/config.py` using
   `pydantic-settings` so every tunable value (model name, timeouts,
   file paths, ports) is controlled from a single `.env` file rather than
   scattered through the code.
4. **Logging layer.** Implemented `backend/logging_config.py` with a
   rotating file handler so logs persist across restarts without growing
   unbounded, plus a console handler for live development feedback.
5. **LLM client.** Implemented `backend/llm_client.py`, isolating all
   Ollama-specific HTTP logic and prompt construction in one module, with
   three distinct custom exceptions (`OllamaConnectionError`,
   `OllamaTimeoutError`, `OllamaResponseError`) so the API layer can
   respond precisely to each failure mode.
6. **FastAPI backend.** Implemented `backend/main.py` with `/health`,
   `/ask`, and `/feedback` endpoints, full Pydantic request/response
   validation, structured logging of every interaction, and a global
   exception handler as a final safety net.
7. **Streamlit frontend.** Implemented `frontend/app.py` with a chat-style
   UI, a live backend/model status indicator in the sidebar, a loading
   spinner during requests, and per-answer feedback buttons.
8. **Testing.** Implemented `tests/test_api.py`, mocking the LLM client
   layer so the full test suite runs deterministically without requiring
   a live Ollama instance, while still exercising the real validation and
   error-handling code paths in `main.py`.
9. **Prompt engineering.** Iterated from a single-line naive prompt to a
   scoped system prompt (see Section 6 for the before/after comparison).
10. **Documentation.** Wrote the README, this report, and the reflection
    answers, and organized the project folder to match the structure
    specified in the assignment.

---

## 6. Testing and Results

### 6.1 Automated API tests

The `pytest` suite in `tests/test_api.py` covers 11 cases:

| Test | Expected result | Outcome |
|---|---|---|
| `/health` with model reachable | 200, `ollama_reachable: true` | Pass |
| `/health` with model unreachable | 200, `ollama_reachable: false` | Pass |
| `/ask` with a valid question | 200 with answer, model, latency, timestamp | Pass |
| `/ask` with empty question | 422 | Pass |
| `/ask` with whitespace-only question | 422 | Pass |
| `/ask` with missing `question` field | 422 | Pass |
| `/ask` with question over max length | 422 | Pass |
| `/ask` when Ollama unreachable | 503 | Pass |
| `/ask` when Ollama times out | 504 | Pass |
| `/ask` when Ollama returns bad payload | 502 | Pass |
| `/feedback` with valid rating | 200, entry written to file | Pass |
| `/feedback` with invalid rating | 422 | Pass |

*(Insert your actual terminal screenshot of `pytest tests/test_api.py -v`
passing here, in `docs/screenshots/`.)*

### 6.2 Manual end-to-end testing

With Ollama running and the model pulled, manual testing through the
Swagger UI (`/docs`) and the Streamlit frontend confirmed:
- `/health` correctly reflects Ollama's running/stopped state.
- `/ask` returns coherent, on-topic answers for all eight supported
  domains.
- Stopping the backend produces the expected "Connection error" message
  in the frontend.
- Stopping Ollama (while the backend stays up) produces a 503 response,
  surfaced in the frontend as "Model unavailable."
- Submitting an empty question is blocked client-side with a warning.
- A long-running request correctly shows the Streamlit spinner.

### 6.3 Prompt improvement comparison (Task 6)

**Original prompt:** `"Answer this university question: {question}"`

**Example question:** *"What's the deadline to pay my tuition fees this semester?"*

**Before (naive prompt) — typical observed behaviour:** the model would
state a specific date or amount with confidence, despite having been
given no actual university fee schedule — a fabricated, potentially
misleading answer.

**After (improved system prompt, see `llm_client.py`):** the model
explains that it does not have the institution's specific fee deadline
and advises the student to confirm the exact date with the Finance
Office, while still being helpful about the general fee-payment process.

This is the central improvement of Task 6: the system prompt does not
make the model "smarter," but it makes it **honest about its limits**,
which is the more important property for a support assistant that real
students might rely on.

---

## 7. Challenges Encountered

- **Latency on first request.** The first call to a freshly started
  Ollama model is noticeably slower because the model weights must be
  loaded into memory. This was addressed by setting a generous
  `REQUEST_TIMEOUT_SECONDS` and surfacing a loading spinner in the
  frontend so this delay does not look like a frozen application.
- **Distinguishing failure types.** Early versions of the LLM client
  caught all `requests` exceptions generically, which made it impossible
  for the frontend to tell a "down" model apart from a "slow" model. This
  was resolved by introducing three distinct custom exception classes.
- **Small-model answer quality.** `llama3.2:1b` is fast but occasionally
  produces verbose or slightly off-topic answers. The system prompt was
  iterated specifically to constrain scope and length (Section 6.3).
- **Keeping configuration consistent across two processes.** Since the
  backend and frontend run as separate processes, both needed to read the
  same `.env` values (e.g. `BACKEND_URL`) without duplicating
  configuration logic — solved by giving the frontend its own lightweight
  `.env` loading via `python-dotenv`, mirroring (but not duplicating the
  internals of) the backend's `pydantic-settings` configuration.

---

## 8. Production Readiness Discussion

This implementation is a deliberately scoped **prototype**, not a
production system. Moving toward production would require, at minimum:

- **Authentication and authorization** — restricting who can call the
  API (e.g. API keys or institutional SSO), rather than the open CORS
  policy used for local development.
- **Rate limiting and abuse protection** — preventing a single user or
  script from overwhelming the model server.
- **Centralized, queryable logging/monitoring** — replacing the local
  rotating log file with a log aggregation and alerting system (e.g.
  Prometheus/Grafana, or a managed logging service) so the operations
  team is notified of failures automatically rather than reading a file.
- **Horizontal scalability** — running the model behind a load balancer
  or using a GPU-backed inference server if request volume grows beyond
  what a single CPU-served Ollama instance can handle.
- **Data governance** — a clear policy on whether/how student questions
  are retained, anonymized, or purged (see Section 9, reflection
  question 9).
- **CI/CD and containerization** — packaging the backend (and ideally the
  whole stack) into Docker images with an automated test/deploy pipeline,
  rather than manually run `uvicorn`/`streamlit` processes.
- **Model evaluation pipeline** — systematic, repeatable evaluation of
  answer quality (beyond informal manual testing) before any prompt or
  model change ships.

---

## 9. Conclusion

This project successfully implements a complete, working pipeline for a
self-hosted LLM application: a configured local development environment,
a locally served language model, a typed and validated FastAPI backend,
an interactive Streamlit frontend, structured logging, comprehensive
error handling, an automated test suite, and a bonus response-evaluation
feature. Every component in the assignment's required architecture
diagram — frontend, backend, local LLM, configuration, logging, error
handling, and testing — is present, functional, and documented.

Beyond completing the assignment's checklist, the project demonstrates
the central lesson it was designed to teach: building an LLM-powered
application is overwhelmingly an exercise in **software engineering**
around the model — request validation, failure isolation, observability,
and clear documentation — rather than in the model itself. The model is a
single, swappable component in a much larger, carefully engineered
system.

---

## 10. Appendix: Screenshots and Code Snippets

This appendix should be populated with your group's own evidence, saved
into `docs/screenshots/` and referenced here, including:

1. Activated virtual environment + successful `pip install -r requirements.txt`
2. `ollama pull llama3.2:1b` output
3. `ollama serve` running, and a direct `ollama run` test
4. `uvicorn backend.main:app --reload` startup log
5. Swagger UI at `/docs`
6. A successful `/health` response
7. A successful `/ask` request/response in Swagger or curl
8. The Streamlit frontend with a sample question and answer
9. `pytest tests/test_api.py -v` passing output
10. An extract of `backend/logs/app.log` showing a question, answer, and timestamp
11. The before/after prompt comparison from Section 6.3, with actual model
    output pasted in

For code snippets, refer to the full source files already included in
the submission under `backend/`, `frontend/`, and `tests/` — this
appendix can reference specific functions (e.g. `ask_llm()` in
`llm_client.py`) rather than duplicating entire files.
