"""Application configuration using pydantic-settings.

Loads from .env file with fallback defaults. All settings are centralized here
to maintain a single source of truth for runtime configuration.
"""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-20250514",
    "openai": "gpt-4o-mini",
}


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Attributes:
        llm_provider: "anthropic" or "openai"
        anthropic_api_key: Anthropic API key
        openai_api_key: OpenAI API key
        model_name: Override model name (empty = use DEFAULT_MODELS)
        max_iterations: Max ReAct loop iterations
        db_path: SQLite database file path
        memory_dir: Directory for markdown memory files
        working_max_per_conv: Max messages per conversation in working memory
        rag_enabled: Enable RAG retriever
        retriever_provider: Retriever backend name
        verification_enabled: Enable self-verification
        verifier_soft_fallback: Allow Stage 3 LLM fallback
        verifier_sampling_rate: Stage 3 proactive sampling rate (0.0-1.0)
        log_level: Logging level
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    llm_provider: str = "anthropic"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = ""  # Custom base URL for OpenAI-compatible APIs (e.g. ZhiPu)
    model_name: str = ""
    llm_max_tokens: int = 4096
    max_iterations: int = 10

    # Memory
    db_path: str = "memory/agent.db"
    memory_dir: str = "memory"
    working_max_per_conv: int = 50

    # RAG
    rag_enabled: bool = True
    retriever_provider: str = "fts5"

    # Verifier
    verification_enabled: bool = True
    verifier_soft_fallback: bool = True
    verifier_sampling_rate: float = 0.1

    # Fault Injection (evaluation)
    inject_failure: str = ""  # Tool name to inject failure into (e.g. "write_note")

    # Notes
    notes_dir: str = "memory/notes"

    # General
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    @field_validator("llm_provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        allowed = {"anthropic", "openai"}
        if v not in allowed:
            raise ValueError(f"llm_provider must be one of {allowed}, got '{v}'")
        return v

    @field_validator("max_iterations")
    @classmethod
    def validate_max_iterations(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"max_iterations must be >= 1, got {v}")
        return v

    @field_validator("verifier_sampling_rate")
    @classmethod
    def validate_sampling_rate(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"verifier_sampling_rate must be 0.0-1.0, got {v}")
        return v

    def resolved_model(self) -> str:
        """Return configured model or provider default.

        Returns:
            Model name string, never empty.
        """
        if self.model_name:
            return self.model_name
        return DEFAULT_MODELS.get(self.llm_provider, DEFAULT_MODELS["openai"])
