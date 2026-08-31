"""NeoClips configuration management using pydantic-settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: Literal["development", "production"] = "development"
    app_name: str = "neoclips"
    log_level: str = "INFO"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8020

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://neoclips:neoclips@localhost:5432/neoclips"
    )
    database_pool_size: int = 5
    database_max_overflow: int = 10

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")

    # Celery
    celery_queue_name: str = "neoclips"
    celery_worker_concurrency: int = 1
    celery_worker_prefetch_multiplier: int = 1

    # CORS - restrictive defaults, explicit configuration required for production
    cors_origins: list[str] = Field(default=["http://localhost:3000", "http://localhost:8080"])
    cors_allow_credentials: bool = True
    cors_allow_methods: list[str] = Field(default=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    cors_allow_headers: list[str] = Field(default=["*"])

    # Media Indexer integration
    media_indexer_base_url: str = Field(default="http://localhost:8000")
    media_indexer_timeout_seconds: int = 30
    media_indexer_project_name: str = "NeoClips Managed Sources"
    media_indexer_initial_index_timeout_seconds: int = 600
    media_indexer_transcription_timeout_seconds: int = 1800
    media_indexer_poll_interval_seconds: int = 5

    # Video Composer (future stage)
    video_composer_url: str | None = None

    # LiteLLM HTTP proxy
    litellm_base_url: str = Field(default="http://localhost:4000")
    litellm_api_key: str | None = None
    litellm_timeout_seconds: int = 60
    litellm_model: str = Field(default="openai/gpt-4o-mini", description="LLM model for clip discovery (format: provider/model)")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is a valid Python logging level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper_v = v.upper()
        if upper_v not in valid_levels:
            raise ValueError(f"Invalid log level: {v}. Must be one of {valid_levels}")
        return upper_v

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.app_env == "production"

    @property
    def database_url_sync(self) -> str:
        """Get synchronous database URL for Alembic."""
        url = str(self.database_url)
        return url.replace("+asyncpg", "")


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Singleton for convenient access
settings = get_settings()
