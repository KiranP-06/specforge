"""Application settings, loaded from environment variables (12-factor)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "SPECForge"
    environment: str = "dev"
    version: str = "1.0.0"
    git_sha: str = "local"

    # Database / queue
    database_url: str = "sqlite:///./specforge.db"
    redis_url: str = "redis://localhost:6379/0"
    # When true, background jobs run in-process (dev/tests); otherwise via Celery.
    inline_jobs: bool = True
    # Dev/tests create tables on startup; production sets this false and runs Alembic migrations.
    auto_create_tables: bool = True

    # Security
    jwt_secret: str = "dev-only-secret-change-me-in-production-please"
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60 * 12
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    # LLM provider: heuristic | openai | anthropic
    #  - heuristic: fully offline, deterministic, no API key needed
    #  - openai: any OpenAI-compatible endpoint (OpenAI, Groq, OpenRouter, Ollama, Gemini-compat)
    llm_provider: str = "heuristic"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: int = 120
    llm_max_repair_attempts: int = 2

    # ML layer (optional heavy models; falls back to lightweight methods if absent)
    use_transformer_models: bool = False
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    nli_model: str = "cross-encoder/nli-deberta-v3-xsmall"
    duplicate_threshold: float = 0.86
    max_self_check_iterations: int = 3

    # Storage: local | s3
    storage_backend: str = "local"
    storage_local_dir: str = "./data"
    s3_bucket: str = ""
    aws_region: str = "us-east-1"
    max_upload_mb: int = 10

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


@lru_cache
def get_settings() -> Settings:
    return Settings()
