from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Uses pydantic-settings so every config value is typed and validated at startup.
    Missing required values produce a clear error instead of a runtime surprise.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_log_level: str = "INFO"
    # Opt-in bypass for the MFA enrolment gate in local dev. Production must
    # NEVER set this to True — spec §3.3 mandates TOTP for admin/AI_analyser
    # roles. Tests leave this False so they can still assert the MFA flow.
    dev_bypass_mfa: bool = False

    # Database
    database_url: str
    database_echo: bool = False

    # Security
    jwt_secret_key: str
    jwt_access_token_minutes: int = 15
    jwt_refresh_token_days: int = 7

    # MFA
    mfa_issuer: str = "PFL Finance Credit AI"

    # CORS
    cors_origins: str = "http://localhost:3000"

    # AWS / LocalStack
    aws_region: str = "ap-south-1"
    aws_s3_endpoint_url: str | None = None  # None = real AWS; set for LocalStack
    aws_s3_public_endpoint_url: str | None = None  # Host-reachable override for presigned URLs served to the browser; falls back to aws_s3_endpoint_url
    aws_sqs_endpoint_url: str | None = None
    aws_ses_endpoint_url: str | None = None
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"
    s3_bucket: str = "pfl-cases-dev"
    sqs_ingestion_queue: str = "pfl-ingestion-dev"
    sqs_ingestion_dlq: str = "pfl-ingestion-dev-dlq"
    presigned_url_expires_seconds: int = 900
    max_zip_size_bytes: int = 100 * 1024 * 1024  # 100 MiB
    max_artifact_size_bytes: int = 50 * 1024 * 1024  # 50 MiB default for additional files
    dev_auto_create_aws_resources: bool = False  # startup creates bucket/queue if True

    # SES
    ses_sender: str = "no-reply@pflfinance.com"
    ses_verify_on_startup: bool = True

    # Worker
    worker_poll_interval_seconds: int = 20
    worker_concurrency: int = 1

    # Ingestion feature flags (M5 flips these)
    enable_bank_statement_deep_parse: bool = False
    enable_photo_classification: bool = False
    enable_kyc_video_analysis: bool = False

    # Web app base URL (for email links)
    app_base_url: str = "http://localhost:8000"

    # Session cookies (M4)
    cookie_secure: bool = False  # True in prod; False in dev/local
    cookie_domain: str | None = None  # e.g., ".pflfinance.com" in prod
    refresh_cookie_max_age_seconds: int = 7 * 24 * 3600  # 7d
    csrf_cookie_max_age_seconds: int = 7 * 24 * 3600  # 7d

    # Anthropic / Decisioning (M5)
    anthropic_api_key: str = ""  # required when decisioning_enabled=True
    anthropic_base_url: str | None = None
    anthropic_default_timeout_s: int = 120
    anthropic_max_retries: int = 3

    # Decisioning feature flags (M5)
    decisioning_enabled: bool = False
    decisioning_shadow_only: bool = True
    decisioning_cost_cap_usd: float = 1.50
    decisioning_cost_abort_usd: float = 2.00
    decisioning_cache_ttl_seconds: int = 300
    decisioning_max_retries: int = 3
    decisioning_step_flags: dict[str, bool] = {}  # empty = all steps enabled

    # Decisioning SQS (M5)
    sqs_decisioning_queue: str = "pfl-decisioning-jobs"
    sqs_decisioning_dlq: str = "pfl-decisioning-dlq"
    decisioning_queue_url: str = ""  # required when decisioning_enabled=True
    decisioning_dlq_url: str = ""

    # pgvector / case library (M5)
    pgvector_feature_dimensions: int = 8
    case_library_retrieval_k: int = 10
    case_library_similarity_threshold: float = 0.70

    # MRP lookup (M5)
    mrp_fuzzy_match_threshold: float = 0.70

    # 4-Level Pre-Phase-1 Verification Gate (Phase A: L1 Address)
    verification_enabled: bool = True
    google_maps_api_key: str = ""  # required when L1 GPS reverse-geocode is active
    google_maps_timeout_seconds: int = 8
    # Confidence threshold for Step 11 auto-apply. Raised from 60 → 70 in
    # Phase E: confidence below this bucket escalates to MD, which feeds the
    # learning loop. Per MD's dump: "above 70% gives verdict, below goes to MD
    # for feedback and learning and improvement loop".
    decisioning_confidence_auto_threshold: int = 70

    @field_validator("jwt_secret_key")
    @classmethod
    def _validate_jwt_key_length(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError(
                "JWT_SECRET_KEY must be at least 32 characters. "
                "Generate one with: openssl rand -hex 32"
            )
        return v

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # env vars fill required fields
