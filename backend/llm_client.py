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

from backend.config import settings
from backend.logging_config import get_logger

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
    """Combine the system prompt and the user's question into one prompt.

    Ollama's /api/generate endpoint takes a single prompt string, so the
    system instructions and the user question are concatenated with a clear
    separator the model can use to distinguish instructions from content.
    """
    return f"{SYSTEM_PROMPT}\n\nStudent question: {question}\n\nAnswer:"


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
        response = requests.post(
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
        response = requests.get(f"{settings.ollama_host}/api/tags", timeout=5)
        return response.status_code == 200
    except requests.exceptions.RequestException as exc:
        logger.warning("Ollama health check failed: %s", exc)
        return False
