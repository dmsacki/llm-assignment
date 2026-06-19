"""
Centralized application configuration.

All tunable values are loaded from environment variables (via a local .env
file) rather than hardcoded, so the same codebase can move between
development, testing, and production environments without code changes.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = one level above this file's parent (backend/ -> project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Strongly-typed application settings.

    Values are read from a `.env` file at the project root, falling back to
    the defaults defined below if a variable is not set.
    """

    # --- Ollama / LLM settings ---
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:1b"

    # --- Request behaviour ---
    request_timeout_seconds: int = 30
    max_question_length: int = 500

    # --- Logging ---
    log_level: str = "INFO"
    log_file_path: str = "backend/logs/app.log"
    feedback_file_path: str = "backend/logs/feedback.jsonl"

    # --- API server ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # --- Frontend ---
    backend_url: str = "http://localhost:8000"

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def resolved_log_path(self) -> Path:
        """Return an absolute, OS-correct path for the log file."""
        path = Path(self.log_file_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    def resolved_feedback_path(self) -> Path:
        """Return an absolute, OS-correct path for the feedback file."""
        path = Path(self.feedback_file_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path


# Single shared settings instance imported throughout the backend.
settings = Settings()
