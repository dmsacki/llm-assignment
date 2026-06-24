"""
LLM client for communicating with a locally hosted Ollama model.

This module is the only place in the codebase that talks to Ollama. It is
responsible for:
  - building the prompt sent to the model (Task 6: prompt engineering)
  - making the HTTP call to the local Ollama server
  - translating low-level network/HTTP errors into a small set of
    well-defined exceptions that `main.py` can map to clean HTTP responses

----------------------------------------------------------------------------
Task 6 — Prompt Improvement (for the report / submission evidence)
----------------------------------------------------------------------------
ORIGINAL (naive) prompt used during early development:

    "Answer this university question: {question}"

Problems observed with the original prompt:
  - The model would answer questions far outside university-support scope
    (e.g. general trivia, coding help) instead of staying on topic.
  - It would confidently invent specific deadlines, fees, and policies
    that were never provided, rather than admitting uncertainty.
  - Responses were inconsistent in length: sometimes one line, sometimes
    a multi-paragraph essay for a simple question.

IMPROVED prompt (implemented below as SYSTEM_PROMPT):
  - Explicitly scopes the assistant to the 8 required university domains.
  - Instructs the model to clearly say when it does not have enough
    information, instead of fabricating specifics.
  - Constrains tone (concise, helpful, student-facing) and length.
  - Separates persistent instructions (system prompt) from the per-request
    question, which is standard practice for production LLM applications.

A side-by-side before/after response comparison (using the same question)
is included in docs/report.md, Section 6 (Testing and Results).
----------------------------------------------------------------------------
"""

import time
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from backend.config import settings
from backend.logging_config import get_logger
from backend.rag import retrieve_relevant_chunks

logger = get_logger()

SYSTEM_PROMPT = """You are the University Student Support Assistant, a helpful and \
concise virtual assistant for university students.

You ONLY answer questions related to the following university service areas:
1. Course registration
2. Examination rules
3. Library services
4. ICT support
5. Hostel application
6. Fee payment
7. Academic calendar
8. Student conduct

Rules you must follow:
- If a question is outside these 8 areas, politely say it is outside your \
    scope and suggest the student contact the relevant university office.
- Never invent specific dates, fees, or policy numbers you were not given. \
    If you are not certain of an exact detail, say so clearly and recommend the \
    student confirm with the relevant office (e.g. Registrar, Library, ICT \
    Helpdesk, Hostel Office, Finance Office, Dean of Students).
- For questions about course registration, prefer and reference ARIS 3 
    (aris3.udsm.ac.tz) as the canonical registration portal; when unsure,
    instruct the student to check ARIS 3 or contact the Registrar's office.
- Keep answers concise and practical: 2-5 sentences unless the student asks \
    for more detail.
- Use a friendly, professional tone appropriate for talking to a student.
"""


class OllamaConnectionError(Exception):
    """Raised when the Ollama server cannot be reached at all."""


class OllamaTimeoutError(Exception):
    """Raised when Ollama does not respond within the configured timeout."""


class OllamaResponseError(Exception):
    """Raised when Ollama responds, but with an unexpected/invalid payload."""


@dataclass
class LLMAnswer:
    """Structured result returned from the LLM for a single question."""

    answer: str
    model: str
    latency_ms: int


def _build_prompt(question: str) -> str:
    """Combine the system prompt, optional retrieval context, and the user's question.

    Ollama's /api/generate endpoint takes a single prompt string, so the
    system instructions and the user question are concatenated with a clear
    separator the model can use to distinguish instructions from content.
    """
    chunks = retrieve_relevant_chunks(question)
    if chunks:
        reference_text = "\n\nReference information (use this if relevant to the question):\n"
        for chunk in chunks:
            reference_text += f"\n{chunk['title']}:\n{chunk['content']}\n"
        return f"{SYSTEM_PROMPT}{reference_text}\nStudent question: {question}\n\nAnswer:"

    return f"{SYSTEM_PROMPT}\n\nStudent question: {question}\n\nAnswer:"


# Configure a single Session with retries/backoff to make transient failures
# and brief model overloads less likely to cause immediate request failures.
_RETRY_STRATEGY = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["HEAD", "GET", "OPTIONS", "POST"],
)

_ADAPTER = HTTPAdapter(max_retries=_RETRY_STRATEGY)
_SESSION = requests.Session()
_SESSION.mount("http://", _ADAPTER)
_SESSION.mount("https://", _ADAPTER)


def ask_llm(question: str) -> LLMAnswer:
    """Send a question to the local Ollama model and return its answer.

    Raises:
        OllamaConnectionError: Ollama is not running / unreachable.
        OllamaTimeoutError: Ollama did not respond in time.
        OllamaResponseError: Ollama responded with an unexpected payload.
    """
    url = f"{settings.ollama_host}/api/generate"
    payload = {
        "model": settings.ollama_model,
        "prompt": _build_prompt(question),
        "stream": False,
    }

    start = time.monotonic()
    try:
        response = _SESSION.post(
            url,
            json=payload,
            timeout=settings.request_timeout_seconds,
        )
    except requests.exceptions.Timeout as exc:
        logger.error("Ollama request timed out after %ss", settings.request_timeout_seconds)
        raise OllamaTimeoutError(
            f"The model did not respond within {settings.request_timeout_seconds} seconds."
        ) from exc
    except requests.exceptions.ConnectionError as exc:
        logger.error("Could not connect to Ollama at %s: %s", settings.ollama_host, exc)
        raise OllamaConnectionError(
            f"Could not reach the local LLM server at {settings.ollama_host}. "
            "Make sure Ollama is running (`ollama serve`) and the model is pulled."
        ) from exc
    except requests.exceptions.RequestException as exc:
        # Catch-all for other request/session related errors (including retry failures)
        logger.error("Request to Ollama failed: %s", exc)
        raise OllamaResponseError("Failed to communicate with the local LLM server.") from exc

    latency_ms = int((time.monotonic() - start) * 1000)

    if response.status_code != 200:
        logger.error("Ollama returned status %s: %s", response.status_code, response.text)
        raise OllamaResponseError(
            f"The local LLM server returned an error (status {response.status_code})."
        )

    try:
        data = response.json()
        answer_text = data["response"].strip()
    except (ValueError, KeyError) as exc:
        logger.error("Unexpected Ollama response payload: %s", response.text)
        raise OllamaResponseError("Received an unreadable response from the local LLM.") from exc

    if not answer_text:
        raise OllamaResponseError("The local LLM returned an empty answer.")

    return LLMAnswer(answer=answer_text, model=settings.ollama_model, latency_ms=latency_ms)


def check_ollama_health() -> bool:
    """Check whether the Ollama server is reachable.

    Used by the /health endpoint. Returns True if Ollama responds at all,
    False otherwise (does not raise).
    """
    try:
        response = _SESSION.get(f"{settings.ollama_host}/api/tags", timeout=5)
        return response.status_code == 200
    except requests.exceptions.RequestException as exc:
        logger.warning("Ollama health check failed: %s", exc)
        return False


def pre_warm_model(timeout: int | None = None) -> bool:
    """Attempt a small generate request to ensure the model is loaded.

    Returns True if the model responded, False otherwise. This is intended
    to be a cheap 'warm-up' call invoked at application startup so the first
    real user request is less likely to hit model load latency.
    """
    url = f"{settings.ollama_host}/api/generate"
    payload = {"model": settings.ollama_model, "prompt": "Hello", "stream": False}
    try:
        resp = _SESSION.post(url, json=payload, timeout=timeout or settings.request_timeout_seconds)
        if resp.status_code == 200:
            logger.info("Pre-warm generate succeeded for model %s", settings.ollama_model)
            return True
        logger.warning("Pre-warm generate returned status %s", resp.status_code)
    except requests.exceptions.RequestException as exc:
        logger.warning("Pre-warm generate failed: %s", exc)
    return False
