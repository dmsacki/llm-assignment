"""
API test suite for the University Student Support Assistant backend.

These tests use FastAPI's TestClient and monkeypatch the LLM client layer,
so the full suite runs quickly and deterministically without requiring a
live Ollama server. This satisfies Task 5 (API testing) and Task 7
(verifying error-handling behaviour) in a repeatable, automated way.

Run with:
    pytest tests/test_api.py -v
"""

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.llm_client import (
    LLMAnswer,
    OllamaConnectionError,
    OllamaResponseError,
    OllamaTimeoutError,
)

client = TestClient(main.app)


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------
def test_health_when_ollama_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """/health should report ollama_reachable=True when the model is up."""
    monkeypatch.setattr(main, "check_ollama_health", lambda: True)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["api_status"] == "ok"
    assert body["ollama_reachable"] is True
    assert "model" in body


def test_health_when_ollama_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """/health should still return 200, but flag ollama_reachable=False."""
    monkeypatch.setattr(main, "check_ollama_health", lambda: False)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["ollama_reachable"] is False


# ---------------------------------------------------------------------------
# /ask - success case
# ---------------------------------------------------------------------------
def test_ask_valid_question_returns_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid question should return a 200 with the expected answer fields."""
    fake_answer = LLMAnswer(answer="You can register via the student portal.", model="llama3.2:1b", latency_ms=120)
    monkeypatch.setattr(main, "ask_llm", lambda question: fake_answer)

    response = client.post("/ask", json={"question": "How do I register for courses?"})

    assert response.status_code == 200
    body = response.json()
    assert body["question"] == "How do I register for courses?"
    assert body["answer"] == fake_answer.answer
    assert body["model"] == "llama3.2:1b"
    assert body["latency_ms"] == 120
    assert "timestamp" in body


# ---------------------------------------------------------------------------
# /ask - invalid request handling
# ---------------------------------------------------------------------------
def test_ask_empty_question_returns_422() -> None:
    """An empty question string should be rejected with a 422 status."""
    response = client.post("/ask", json={"question": ""})
    assert response.status_code == 422


def test_ask_whitespace_only_question_returns_422() -> None:
    """A whitespace-only question should also be treated as empty."""
    response = client.post("/ask", json={"question": "   "})
    assert response.status_code == 422


def test_ask_missing_question_field_returns_422() -> None:
    """Omitting the 'question' field entirely should fail validation."""
    response = client.post("/ask", json={})
    assert response.status_code == 422


def test_ask_question_too_long_returns_422() -> None:
    """A question exceeding the configured max length should be rejected."""
    from backend.config import settings

    too_long = "a" * (settings.max_question_length + 1)
    response = client.post("/ask", json={"question": too_long})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# /ask - LLM-layer failure handling
# ---------------------------------------------------------------------------
def test_ask_when_model_unreachable_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """If Ollama is not running, /ask should return 503 with a clear message."""

    def raise_connection_error(question: str) -> None:
        raise OllamaConnectionError("Could not reach the local LLM server.")

    monkeypatch.setattr(main, "ask_llm", raise_connection_error)

    response = client.post("/ask", json={"question": "What are the library hours?"})

    assert response.status_code == 503
    assert response.json()["error"] == "model_unavailable"


def test_ask_when_model_times_out_returns_504(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the model takes too long, /ask should return 504."""

    def raise_timeout(question: str) -> None:
        raise OllamaTimeoutError("The model did not respond in time.")

    monkeypatch.setattr(main, "ask_llm", raise_timeout)

    response = client.post("/ask", json={"question": "What are the exam rules?"})

    assert response.status_code == 504
    assert response.json()["error"] == "model_timeout"


def test_ask_when_model_returns_bad_payload_returns_502(monkeypatch: pytest.MonkeyPatch) -> None:
    """If Ollama returns something unreadable, /ask should return 502."""

    def raise_response_error(question: str) -> None:
        raise OllamaResponseError("Received an unreadable response.")

    monkeypatch.setattr(main, "ask_llm", raise_response_error)

    response = client.post("/ask", json={"question": "How do I apply for a hostel?"})

    assert response.status_code == 502
    assert response.json()["error"] == "model_invalid_response"


# ---------------------------------------------------------------------------
# /feedback (bonus: response evaluation)
# ---------------------------------------------------------------------------
def test_feedback_with_valid_rating_is_saved(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """A valid Good/Average/Poor rating should be persisted and return 200."""
    feedback_file = tmp_path / "feedback.jsonl"
    monkeypatch.setattr(main.settings, "feedback_file_path", str(feedback_file))

    response = client.post(
        "/feedback",
        json={
            "question": "How do I pay my fees?",
            "answer": "You can pay via the university finance portal.",
            "rating": "Good",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "saved"
    assert feedback_file.exists()
    assert "Good" in feedback_file.read_text(encoding="utf-8")


def test_feedback_with_invalid_rating_returns_422() -> None:
    """A rating outside Good/Average/Poor should fail validation."""
    response = client.post(
        "/feedback",
        json={"question": "Test?", "answer": "Test answer.", "rating": "Excellent"},
    )
    assert response.status_code == 422
