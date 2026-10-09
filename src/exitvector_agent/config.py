"""Environment-backed application configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="EXITVECTOR_",
        env_file=None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    environment: str = Field(
        default="development",
        validation_alias=AliasChoices("EXITVECTOR_ENV", "EXITVECTOR_ENVIRONMENT"),
    )
    database_url: str = Field(default="sqlite:///./data/exitvector.db")
    audience_provider: Literal["auto", "mock", "database", "archive"] = Field(
        default="auto", validation_alias=AliasChoices("AUDIENCE_PROVIDER", "EXITVECTOR_AUDIENCE_PROVIDER"))
    audience_archive_path: str | None = Field(
        default=None, validation_alias=AliasChoices("AUDIENCE_ARCHIVE_PATH", "EXITVECTOR_AUDIENCE_ARCHIVE_PATH"))
    scan_interval_seconds: int = Field(default=600, ge=1)
    notify_threshold: int = Field(default=75, ge=0, le=100)
    regivion_base_url: str = Field(
        default="http://localhost:8000",
        validation_alias=AliasChoices("REGIVION_BASE_URL", "EXITVECTOR_REGIVION_BASE_URL"),
    )
    regivion_api_key: str | None = Field(
        default=None,
        repr=False,
        validation_alias=AliasChoices("REGIVION_API_KEY", "EXITVECTOR_REGIVION_API_KEY"),
    )
    regivion_timeout_seconds: float = Field(
        default=10.0,
        ge=1.0,
        validation_alias=AliasChoices("REGIVION_TIMEOUT_SECONDS", "EXITVECTOR_REGIVION_TIMEOUT_SECONDS"),
    )
    telegram_bot_token: str | None = Field(default=None, validation_alias=AliasChoices("TELEGRAM_BOT_TOKEN", "EXITVECTOR_TELEGRAM_BOT_TOKEN"))
    telegram_chat_id: str | None = Field(default=None, validation_alias=AliasChoices("TELEGRAM_CHAT_ID", "EXITVECTOR_TELEGRAM_CHAT_ID"))
    ai_provider: str = Field(default="mock", validation_alias=AliasChoices("LLM_PROVIDER", "EXITVECTOR_AI_PROVIDER"))
    ai_model: str | None = Field(default=None, validation_alias=AliasChoices("LLM_MODEL", "EXITVECTOR_AI_MODEL"))
    llm_api_key: str | None = Field(default=None, repr=False, validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"))
    llm_timeout_seconds: float = Field(default=30, gt=0, le=120, validation_alias="LLM_TIMEOUT_SECONDS")
    llm_temperature: float | None = Field(default=None, ge=0, le=2, validation_alias="LLM_TEMPERATURE")
    llm_max_generations_per_run: int = Field(default=9, ge=1, le=100, validation_alias="LLM_MAX_GENERATIONS_PER_RUN")
    content_variants_per_opportunity: int = Field(default=3, ge=1, le=3, validation_alias="CONTENT_VARIANTS_PER_OPPORTUNITY")
    max_opportunities_per_run: int = Field(default=20, ge=1, le=100, validation_alias="MAX_OPPORTUNITIES_PER_RUN")
    reddit_enabled: bool = Field(default=False, validation_alias="REDDIT_ENABLED")
    reddit_client_id: str | None = Field(default=None, repr=False, validation_alias=AliasChoices("REDDIT_CLIENT_ID", "EXITVECTOR_REDDIT_CLIENT_ID"))
    reddit_client_secret: str | None = Field(default=None, repr=False, validation_alias=AliasChoices("REDDIT_CLIENT_SECRET", "EXITVECTOR_REDDIT_CLIENT_SECRET"))
    reddit_user_agent: str | None = Field(default=None, validation_alias="REDDIT_USER_AGENT")
    reddit_subreddits: str = Field(default="stocks,investing", validation_alias="REDDIT_SUBREDDITS")
    reddit_request_timeout_seconds: float = Field(default=10, gt=0, le=60, validation_alias="REDDIT_REQUEST_TIMEOUT_SECONDS")
    reddit_max_items_per_scan: int = Field(default=100, ge=1, le=500, validation_alias="REDDIT_MAX_ITEMS_PER_SCAN")
    reddit_min_request_interval_seconds: float = Field(default=1, ge=0.6, le=60, validation_alias="REDDIT_MIN_REQUEST_INTERVAL_SECONDS")
    social_lookback_minutes: int = Field(default=60, ge=1, le=1440, validation_alias="SOCIAL_LOOKBACK_MINUTES")
    regivion_cache_ttl_seconds: float = Field(default=60, ge=0, le=3600, validation_alias="REGIVION_CACHE_TTL_SECONDS")
    regivion_max_age_seconds: float = Field(default=86400, gt=0, validation_alias="REGIVION_MAX_AGE_SECONDS")
    regivion_required: bool = Field(default=True, validation_alias="REGIVION_REQUIRED")
    regivion_contract: Literal["unavailable", "valuation-history", "agent-v1"] = Field(default="agent-v1", validation_alias="REGIVION_CONTRACT")
    market_provider: Literal["disabled", "mock"] = Field(default="disabled", validation_alias="MARKET_PROVIDER")
    provider_circuit_failure_threshold: int = Field(default=3, ge=1, le=20, validation_alias="PROVIDER_CIRCUIT_FAILURE_THRESHOLD")
    provider_circuit_cooldown_seconds: float = Field(default=300, gt=0, le=3600, validation_alias="PROVIDER_CIRCUIT_COOLDOWN_SECONDS")

    agent_scan_interval_minutes: float = Field(default=30, gt=0, validation_alias="AGENT_SCAN_INTERVAL_MINUTES")
    agent_min_interval_seconds: float = Field(default=60, gt=0, validation_alias="AGENT_MIN_INTERVAL_SECONDS")
    agent_run_on_start: bool = Field(default=True, validation_alias="AGENT_RUN_ON_START")
    agent_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO", validation_alias="AGENT_LOG_LEVEL")
    agent_log_dir: Path = Field(default=Path("logs"), validation_alias="AGENT_LOG_DIR")
    agent_data_dir: Path = Field(default=Path("data"), validation_alias="AGENT_DATA_DIR")
    agent_lock_timeout_minutes: float = Field(default=60, gt=0, validation_alias="AGENT_LOCK_TIMEOUT_MINUTES")
    agent_max_errors_per_run: int = Field(default=10, ge=1, validation_alias="AGENT_MAX_ERRORS_PER_RUN")
    agent_provider_max_retries: int = Field(default=2, ge=0, le=5, validation_alias="AGENT_PROVIDER_MAX_RETRIES")
    agent_retry_backoff_seconds: float = Field(default=.1, ge=0, le=5, validation_alias="AGENT_RETRY_BACKOFF_SECONDS")
    agent_provider_timeout_seconds: float = Field(default=10, gt=0, validation_alias="AGENT_PROVIDER_TIMEOUT_SECONDS")
    agent_audience_refresh_enabled: bool = Field(default=False, validation_alias="AGENT_AUDIENCE_REFRESH_ENABLED")
    agent_audience_refresh_interval_hours: float = Field(default=24, gt=0, validation_alias="AGENT_AUDIENCE_REFRESH_INTERVAL_HOURS")
    agent_notify_review_enabled: bool = Field(default=True, validation_alias="AGENT_NOTIFY_REVIEW_ENABLED")
    agent_social_provider: Literal["mock", "live", "mixed"] = Field(default="mock", validation_alias=AliasChoices("SOCIAL_PROVIDER_MODE", "AGENT_SOCIAL_PROVIDER"))
    agent_regivion_provider: Literal["mock", "http", "disabled"] = Field(default="mock", validation_alias=AliasChoices("REGIVION_PROVIDER", "AGENT_REGIVION_PROVIDER"))
    allow_x_posting: bool = Field(default=False, validation_alias="ALLOW_X_POSTING")
    allow_x_follow_actions: bool = Field(default=False, validation_alias="ALLOW_X_FOLLOW_ACTIONS")

    @property
    def database_path(self) -> Path:
        if not self.database_url.startswith("sqlite:///"):
            raise ValueError("Only local SQLite databases are supported")
        if "database_url" not in self.model_fields_set:
            return self.agent_data_dir / "exitvector.db"
        return Path(self.database_url.removeprefix("sqlite:///"))

    def validate_operation(self) -> None:
        if self.allow_x_posting or self.allow_x_follow_actions:
            raise ValueError("X posting and relationship actions must remain disabled")
        production = self.environment.casefold() == "production"
        if production and (self.agent_social_provider != 'live' or self.agent_regivion_provider == 'mock' or self.ai_provider != 'openai' or self.market_provider == 'mock'):
            raise ValueError("Production requires live social and OpenAI, and HTTP Regivion or explicit disabled mode; mock fallback is prohibited")
        if self.agent_social_provider in {'live', 'mixed'}:
            import re
            if not self.reddit_enabled or not all((self.reddit_client_id, self.reddit_client_secret, self.reddit_user_agent)):
                raise ValueError("Live Reddit requires REDDIT_ENABLED and client ID, secret and User-Agent")
            names = self.reddit_subreddits.split(',')
            if not names or len(names) > 10 or any(not re.fullmatch(r'[A-Za-z0-9_]{2,30}', n.strip()) for n in names):
                raise ValueError("REDDIT_SUBREDDITS must contain 1-10 comma-separated community names")
        if self.agent_regivion_provider == 'http':
            from urllib.parse import urlsplit
            import ipaddress
            url = urlsplit(self.regivion_base_url)
            if not url.hostname or url.username or url.password or url.query or url.fragment or url.scheme not in {'http', 'https'}:
                raise ValueError("Regivion requires a valid HTTP base URL without credentials or query strings")
            if 'regivion_base_url' not in self.model_fields_set or not self.regivion_api_key:
                raise ValueError("HTTP Regivion requires explicit REGIVION_BASE_URL and read-only credentials")
            try:
                local = not ipaddress.ip_address(url.hostname).is_global
            except ValueError:
                local = url.hostname in {'localhost'} or url.hostname.endswith(('.localhost', '.local'))
            if production and (url.scheme != 'https' or local):
                raise ValueError("Production Regivion requires the explicitly configured remote HTTPS Hetzner target")
            if self.regivion_contract not in {'valuation-history', 'agent-v1'}:
                raise ValueError("Regivion enrichment API contract unavailable; see REGIVION_INTEGRATION.md")
            if production and (self.regivion_contract != "agent-v1" or url.hostname != "regivion.com" or url.path not in {"", "/"}):
                raise ValueError("Regivion production requires agent-v1 at https://regivion.com; valuation-history lacks dedicated read-only production verification")
        if self.agent_regivion_provider == 'disabled' and self.regivion_required:
            raise ValueError("Disabled Regivion requires explicit REGIVION_REQUIRED=false")
        if self.ai_provider not in {"mock", "rule-based", "openai"}:
            raise ValueError("Unknown LLM provider; choose mock, rule-based or openai explicitly")
        if self.ai_provider == 'openai' and not all((self.llm_api_key, self.ai_model)):
            raise ValueError("OpenAI requires LLM_API_KEY and explicit LLM_MODEL")
        self.database_path

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("environment must not be empty")
        return value.strip()


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Load settings from environment variables and an optional dotenv file."""

    if env_file is None:
        env_file = next((p for p in (Path(".exitvector.env"), Path("exitvector.env")) if p.is_file()), None)
    kwargs = {"_env_file": str(env_file)} if env_file is not None else {}
    return Settings(**kwargs)
