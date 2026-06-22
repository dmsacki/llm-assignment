"""
FastAPI backend for the University Student Support Assistant.

Exposes three endpoints:
    GET  /health    -> reports whether the API and the local LLM are up
    POST /ask        -> sends a student question to the LLM, returns the answer
    POST /feedback   -> records a Good/Average/Poor rating for a given answer

All requests/responses are validated with Pydantic, all outcomes (success
and failure) are logged with a timestamp, and every known failure mode from
the assignment's error-handling table (Task 7) is mapped to a specific,
informative HTTP response instead of a raw stack trace.
"""

import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Request, status
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.config import settings
from backend.llm_client import (
    OllamaConnectionError,
    OllamaResponseError,
    OllamaTimeoutError,
    ask_llm,
    check_ollama_health,
    pre_warm_model,
)
from backend.logging_config import get_logger

logger = get_logger()

@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Lifespan handler that optionally pre-warms the local model."""
    if settings.pre_warm_model:
        import threading

        def _worker() -> None:
            try:
                pre_warm_model(timeout=settings.pre_warm_timeout_seconds)
            except Exception:
                logger.exception("Model pre-warm failed")

        threading.Thread(target=_worker, daemon=True).start()
    yield


app = FastAPI(
    title="University Student Support Assistant API",
    description=(
        "Self-hosted LLM-powered API answering student questions about "
        "course registration, exams, library services, ICT support, "
        "hostel applications, fee payment, the academic calendar, and "
        "student conduct."
    ),
    version="1.0.0",
    lifespan=_lifespan,
)

# Allow the Streamlit frontend (typically on a different port) to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# (pre-warm executed via lifespan handler)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
class AskRequest(BaseModel):
    """Incoming payload for POST /ask."""

    question: str = Field(
        ...,
        min_length=1,
        max_length=settings.max_question_length,
        description="The student's question.",
        examples=["How do I register for courses this semester?"],
    )


class AskResponse(BaseModel):
    """Outgoing payload for POST /ask."""

    question: str
    answer: str
    model: str
    latency_ms: int
    timestamp: str


class HealthResponse(BaseModel):
    """Outgoing payload for GET /health."""

    api_status: Literal["ok"]
    ollama_reachable: bool
    model: str


class FeedbackRequest(BaseModel):
    """Incoming payload for POST /feedback (bonus Task 10, Option E)."""

    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    rating: Literal["Good", "Average", "Poor"]


class FeedbackResponse(BaseModel):
    """Outgoing payload for POST /feedback."""

    status: Literal["saved"]


class ErrorResponse(BaseModel):
    """Standard shape for error payloads returned to the client."""

    error: str
    detail: str


def _now_iso() -> str:
    """Return the current UTC time in ISO 8601 format for logs and responses."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/", tags=["meta"])
def root() -> dict:
    """Simple landing route confirming the API is reachable."""
    return {
        "service": "University Student Support Assistant API",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    """Report whether the API itself and the underlying Ollama model are up."""
    ollama_ok = check_ollama_health()
    logger.info("Health check requested | ollama_reachable=%s", ollama_ok)
    return HealthResponse(
        api_status="ok",
        ollama_reachable=ollama_ok,
        model=settings.ollama_model,
    )


@app.post(
    "/ask",
    response_model=AskResponse,
    responses={
        422: {"model": ErrorResponse, "description": "Invalid or empty question"},
        503: {"model": ErrorResponse, "description": "Local LLM server unreachable"},
        504: {"model": ErrorResponse, "description": "Local LLM took too long to respond"},
        502: {"model": ErrorResponse, "description": "Local LLM returned an invalid response"},
    },
    tags=["assistant"],
)
def ask(payload: AskRequest) -> AskResponse:
    """Send a student's question to the local LLM and return its answer.

    Empty/missing questions never reach this function body: FastAPI rejects
    them at validation time (Pydantic `min_length=1`) with a 422 response.
    """
    question = payload.question.strip()
    if not question:
        # Defensive check in case the question was only whitespace, which
        # passes Pydantic's min_length=1 check but is still "empty" content.
        logger.warning("Rejected whitespace-only question")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": "empty_question", "detail": "Please enter a question."},
        )

    try:
        result = ask_llm(question)
    except OllamaConnectionError as exc:
        logger.error("ask() failed - Ollama unreachable: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "model_unavailable", "detail": str(exc)},
        )
    except OllamaTimeoutError as exc:
        logger.error("ask() failed - Ollama timeout: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content={"error": "model_timeout", "detail": str(exc)},
        )
    except OllamaResponseError as exc:
        logger.error("ask() failed - bad Ollama response: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": "model_invalid_response", "detail": str(exc)},
        )

    timestamp = _now_iso()
    logger.info(
        "QUESTION='%s' | ANSWER='%s' | latency_ms=%s | timestamp=%s",
        question,
        result.answer[:200],
        result.latency_ms,
        timestamp,
    )

    return AskResponse(
        question=question,
        answer=result.answer,
        model=result.model,
        latency_ms=result.latency_ms,
        timestamp=timestamp,
    )


@app.post("/feedback", response_model=FeedbackResponse, tags=["assistant"])
def feedback(payload: FeedbackRequest) -> FeedbackResponse:
    """Persist a Good/Average/Poor rating for a given question/answer pair.

    Feedback is appended as a single JSON line per entry to a feedback file
    on disk, keeping the implementation dependency-free (no database needed
    for this assignment's scope).
    """
    entry = {
        "timestamp": _now_iso(),
        "question": payload.question,
        "answer": payload.answer,
        "rating": payload.rating,
    }

    feedback_path = settings.resolved_feedback_path()
    feedback_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(feedback_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.error("Failed to write feedback entry: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "feedback_write_failed", "detail": "Could not save feedback."},
        )

    logger.info("Feedback recorded | rating=%s", payload.rating)
    return FeedbackResponse(status="saved")


# ---------------------------------------------------------------------------
# Global exception handler (catches anything not explicitly handled above)
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler so unexpected bugs never leak a raw stack trace."""
    logger.exception("Unhandled exception on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "internal_server_error",
            "detail": "Something went wrong on the server. Please try again later.",
        },
    )
