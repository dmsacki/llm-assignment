# Reflection — Industry Production Considerations

*(Task 9 of the IS 365 assignment)*

---

### 1. What are the main components of your deployed LLM system?

The system has five main components, each in its own module so they can be
understood, tested, and replaced independently:

1. **Local LLM (Ollama + `llama3.2:1b`)** — the model serving layer,
   running entirely on local hardware and exposed over a local HTTP API.
2. **LLM client (`backend/llm_client.py`)** — the only module that talks to
   Ollama; owns the system prompt and translates network-level failures
   into application-level exceptions.
3. **FastAPI backend (`backend/main.py`)** — exposes `/health`, `/ask`,
   and `/feedback`, validates all input, logs every interaction, and maps
   every failure mode to a specific HTTP status and message.
4. **Streamlit frontend (`frontend/app.py`)** — the chat interface
   students use, including a live status indicator, loading spinner, and
   feedback buttons.
5. **Cross-cutting infrastructure** — `config.py` (centralized,
   environment-driven settings) and `logging_config.py` (persistent,
   rotating logs), used by the backend throughout.

---

### 2. Why is FastAPI useful in this pipeline?

FastAPI gives this pipeline three things that matter directly for an LLM
application: **automatic request validation** via Pydantic (so a missing
or empty `question` field is rejected before any code that touches the
model even runs), **automatic interactive documentation** at `/docs`
(used directly as submission evidence for Task 3 and Task 5, and useful
for manually testing the API without writing a client), and **async-ready
performance** — if this system needed to serve many concurrent students,
FastAPI's ASGI foundation (via Uvicorn) supports that without a rewrite.
It also encourages a clean separation between the API contract (the
Pydantic models) and the business logic (the LLM client), which made the
error-handling requirements of this assignment straightforward to
implement and test.

---

### 3. What role does your chosen LLM model play?

`llama3.2:1b` is the component that actually generates natural-language
answers from the student's question. It does not store any university
data — it has no built-in knowledge of this specific university's actual
deadlines, fees, or policies — so its role here is closer to a "language
generation engine" than a database. The system prompt constrains *how* it
answers (scope, tone, honesty about uncertainty), but the model itself
is purely the text-generation component, swappable for `phi3` or a larger
model by changing one configuration value, without changing any other
part of the system.

---

### 4. What role does the frontend play?

The Streamlit frontend is the only part of the system a student directly
sees. Its responsibilities are: collecting and lightly validating user
input, calling the backend API, presenting the response in a readable
chat format, and — critically for usability — communicating *system
state* to the user (a "Thinking..." spinner during slow responses, a
live backend/model health indicator in the sidebar, and specific error
messages when something goes wrong). The frontend deliberately contains
no LLM logic itself; it is a thin, replaceable presentation layer over
the backend's API.

---

### 5. What is the difference between running the model locally and using an external API?

Running the model locally via Ollama means the organization controls the
full stack: there is no per-request cost, no internet dependency once the
model is pulled, and no student data leaves local infrastructure — but
the organization is responsible for its own hardware, uptime, model
updates, and scaling. Using an external API (e.g. a hosted commercial
LLM) shifts those operational burdens to the provider and typically gives
access to far more capable models, but introduces per-request cost,
a network/internet dependency, potential data-residency or privacy
concerns (student questions leaving the institution's infrastructure),
and dependency on a third party's uptime and pricing changes. This
project deliberately chose the local route to make those operational
trade-offs visible and hands-on.

---

### 6. What security risks may exist if this system is deployed in an organisation?

Several risks exist in the current prototype that would need to be
addressed before any real deployment: the backend currently has an open
CORS policy (`allow_origins=["*"]`) suitable only for local development;
there is no authentication on any endpoint, so anyone who can reach the
API can use it or flood it with requests; there is no rate limiting,
making the system vulnerable to denial-of-service through repeated
expensive `/ask` calls; logs and feedback files are stored in plain text
on disk with no access control or encryption; and prompt injection is
possible — a student could try to manipulate the system prompt's
instructions through cleverly crafted input. None of these are addressed
in this prototype by design (the assignment's focus is the pipeline, not
hardening), but they are the first items on any production checklist.

---

### 7. What improvements would be needed before deploying this system in production?

Building on Section 8 of the technical report: add authentication
(API keys or institutional single sign-on), restrict CORS to known
frontend origins, add rate limiting per user/IP, containerize the
backend with Docker for consistent, repeatable deployment, replace the
local log file with centralized log aggregation and alerting, add a
proper evaluation pipeline for answer quality before any prompt or model
change ships, and put the model behind a more robust serving setup
(e.g. GPU-backed inference or a managed model-serving platform) if usage
volume grows. A staging environment and a rollback plan for prompt or
model changes would also be necessary.

---

### 8. How would you monitor the system in real-world use?

Real-world monitoring would build on the structured logging already in
place by shipping logs to a centralized system (e.g. an ELK stack,
Grafana Loki, or a managed logging service) rather than reading a local
file. Key metrics to track would include: request volume over time,
`/ask` success vs. error rate broken down by error type (503/504/502),
average and p95 response latency, and the distribution of feedback
ratings from the `/feedback` endpoint as a proxy for answer quality.
Alerting would be configured on the health check (e.g. paging if
`ollama_reachable` stays `false` for more than a few minutes) and on
error-rate spikes, so problems are caught before students notice them.

---

### 9. How would you protect sensitive student information?

Even though this prototype's question/answer content is generally
low-sensitivity (general service questions), a real deployment could see
students include personal details (registration numbers, health
information justifying an exam exception, etc.) in their questions. To
protect this: avoid logging full question/answer text in production (log
metadata — timestamp, latency, status — and only retain content
short-term, separately, with restricted access); encrypt data at rest and
in transit (HTTPS for all traffic, encrypted storage for logs and
feedback); enforce authentication so question history is tied to and only
visible to the asking student and authorized staff; define and enforce a
data retention/deletion policy; and ensure compliance with the
institution's data protection obligations before any production
deployment.

---

### 10. What challenges did you face during implementation?

The main implementation challenges were: handling the noticeably slower
first response from a freshly loaded Ollama model without it appearing
to the user as a frozen application (solved with a generous timeout and a
visible loading spinner); distinguishing different LLM failure modes
(model down vs. slow vs. returning a malformed response) so the frontend
could give specific, useful error messages rather than one generic
"something went wrong" (solved with three distinct custom exception
classes in `llm_client.py`); and managing the small model's tendency to
go off-topic or fabricate specific details, which required iterating the
system prompt (Task 6) rather than just the application code. These
challenges reflect exactly the kind of engineering work the assignment
was designed to surface — the difficulty in an LLM application is rarely
"calling the model," it is everything around that call.
