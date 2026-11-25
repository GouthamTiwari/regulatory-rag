"""All settings for regrag in one place.

Every number here is a *starting value* from docs/SPEC.md section 5; Task 28 tunes some of
them on the golden set. Any field can be overridden by an environment variable of the same
name in upper case (for example `RERANK_TOP_N=6`), usually via the `.env` file.
"""

from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Why here, at import time: boto3 reads credentials from the process environment, not from
# .env, so the file must be loaded before any Bedrock client is created. load_dotenv() never
# overwrites a variable that is already set in the real environment.
load_dotenv()

# v1 uses Amazon first-party models only: this AISPL (India) account can't subscribe to the
# AWS Marketplace models (Claude, Cohere) by card (SPEC decision 7). Nova 2 Lite has no
# in-region option in Mumbai, so it goes through the global inference profile, which is
# also the cheapest prefix (SPEC 2.1).
NOVA_LITE_PROFILE_ID = "global.amazon.nova-2-lite-v1:0"
# Stronger model for the final reported judge run. It has no `global.` profile; `apac.` works.
NOVA_PRO_PROFILE_ID = "apac.amazon.nova-pro-v1:0"


class Settings(BaseSettings):
    # env_ignore_empty: `.env.example` copied as-is has `NAME=` lines; an empty value must
    # mean "use the default", not "set this to an empty string".
    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)

    # --- AWS region and auth (SPEC 2.2, 2.3) -------------------------------------------
    # Mumbai: closest to India, and it has Titan V2 plus Nova through inference profiles.
    aws_region: str = "ap-south-1"
    # Mumbai has no Bedrock reranker, so rerank calls alone go to Tokyo (SPEC decision 8).
    bedrock_rerank_region: str = "ap-northeast-1"
    # Option A, recommended: a Bedrock-only API key that expires on its own.
    aws_bearer_token_bedrock: SecretStr = SecretStr("")
    # Option B: IAM user access keys. Set only one option.
    aws_access_key_id: SecretStr = SecretStr("")
    aws_secret_access_key: SecretStr = SecretStr("")

    # --- Bedrock model IDs (SPEC 2.1) ---------------------------------------------------
    # 1024-dim embeddings, in-region, $0.02 per 1M tokens.
    bedrock_embed_model_id: str = "amazon.titan-embed-text-v2:0"
    # Amazon's own reranker, called in bedrock_rerank_region. Called via InvokeModel because
    # Bedrock API keys can't use the agent-runtime Rerank API. Upgrade: cohere.rerank-v3-5:0.
    bedrock_rerank_model_id: str = "amazon.rerank-v1:0"
    # Router and answer model: cheap and fast enough to call twice per question.
    # Upgrade: global.anthropic.claude-haiku-5-5.
    bedrock_llm_model_id: str = NOVA_LITE_PROFILE_ID
    # Faithfulness judge for development runs. Task 28 sets NOVA_PRO_PROFILE_ID for the final
    # run (upgrade: global.anthropic.claude-sonnet-5-5).
    bedrock_judge_model_id: str = NOVA_LITE_PROFILE_ID

    # --- Local Postgres in Docker (SPEC 4) ------------------------------------------------
    postgres_user: str = "regrag"
    postgres_password: SecretStr = SecretStr("")
    postgres_db: str = "regrag"
    # 5433, not 5432, so it never clashes with a Postgres already installed on the PC.
    postgres_port: int = Field(default=5433, gt=0, lt=65536)
    # Optional full connection string. Secret because it contains the password.
    database_url: SecretStr = SecretStr("")

    # --- Download (SPEC 5) ------------------------------------------------------------------
    # Be polite to government servers: one request every 2 seconds.
    download_delay_s: float = Field(default=2.0, ge=0)
    download_timeout_s: float = Field(default=60.0, gt=0)
    download_retries: int = Field(default=3, ge=0)
    # "Official sources only", enforced in code. Subdomains (www.rbi.org.in) count as the host.
    allowed_download_hosts: tuple[str, ...] = (
        "rbi.org.in",
        "rbidocs.rbi.org.in",
        "gstcouncil.gov.in",
        "cbic-gst.gov.in",
        "taxinformation.cbic.gov.in",
        "cbic.gov.in",
        # GSTN's official help site: GSTR-2B and IMS advisories (task 35).
        "tutorial.gst.gov.in",
    )

    # --- Chunking (SPEC 5) ------------------------------------------------------------------
    # ~400 tokens keeps one rule per chunk and sits well inside the reranker's 4K limit.
    chunk_target_tokens: int = Field(default=400, gt=0)
    # Hard ceiling for ordinary text chunks.
    chunk_max_tokens: int = Field(default=500, gt=0)
    # Overlap so a sentence that straddles a boundary is not lost.
    chunk_overlap_tokens: int = Field(default=60, ge=0)
    # Tables are only split above this size, because a half table is unreadable.
    table_max_tokens: int = Field(default=1000, gt=0)

    # --- Embedding (SPEC 5) -----------------------------------------------------------------
    # Best Titan V2 quality, and well inside pgvector's index limit.
    embed_dimensions: int = 1024
    # Titan takes one text per call, so a few calls in parallel; more would hit throttling.
    embed_concurrency: int = Field(default=4, gt=0)
    # A new account's Titan quota throttles bursts but accepts a steady 1 call/second of
    # real ~300-token chunks (measured 2026-11-16). Raise it once AWS grants a higher quota.
    embed_requests_per_second: float = Field(default=1.0, ge=0)

    # --- Retrieval and fusion (SPEC 5) ------------------------------------------------------
    # 30 per leg gives the reranker enough candidates while costing one billed rerank query.
    keyword_top_k: int = Field(default=30, gt=0)
    vector_top_k: int = Field(default=30, gt=0)
    # k=60 is the value from the original RRF paper; it needs no calibration between legs.
    rrf_k: int = Field(default=60, gt=0)
    fused_top_k: int = Field(default=30, gt=0)
    # Above pgvector's default of 40 so route-filtered searches still return 30 rows.
    hnsw_ef_search: int = Field(default=100, gt=0)

    # --- Rerank, generation, abstention (SPEC 5) --------------------------------------------
    # Enough context for multi-part questions, small enough to keep the prompt cheap.
    rerank_top_n: int = Field(default=8, gt=0)
    # This account's applied quota for Amazon Rerank 1.0 in Tokyo is 2 requests/minute
    # (AWS default 200; "not adjustable" while the account is new). Raise when AWS raises it.
    rerank_requests_per_minute: float = Field(default=2.0, ge=0)
    # Below this top rerank score we abstain. Calibrated on the 20 golden questions with
    # Amazon Rerank (2026-11-16): answerable questions scored 0.058-0.997, out-of-corpus ones
    # 0.0003-0.0007. 0.01 sits between them with a wide margin both ways. (The 0.30 starting
    # guess was made for Cohere and would have refused good questions.) Task 28 re-tunes it.
    abstain_threshold: float = Field(default=0.01, ge=0, le=1)
    # Includes Haiku's thinking tokens, which are billed as output.
    llm_max_tokens: int = Field(default=1500, gt=0)

    @model_validator(mode="after")
    def _check_relationships(self) -> "Settings":
        # Why: a tuning run that sets, say, overlap above the target size would silently
        # produce nonsense chunks. Fail loudly at startup instead.
        if not self.chunk_overlap_tokens < self.chunk_target_tokens <= self.chunk_max_tokens:
            raise ValueError("need chunk_overlap_tokens < chunk_target_tokens <= chunk_max_tokens")
        if self.table_max_tokens < self.chunk_max_tokens:
            raise ValueError("table_max_tokens must be >= chunk_max_tokens")
        if self.rerank_top_n > self.fused_top_k:
            raise ValueError("rerank_top_n cannot exceed fused_top_k")
        return self

    def database_dsn(self) -> str:
        """Connection string for psycopg. Contains the password: never print or log it."""
        if self.database_url.get_secret_value():
            return self.database_url.get_secret_value()
        password = self.postgres_password.get_secret_value()
        # 127.0.0.1, not "localhost": on Windows, localhost tries IPv6 (::1) first, and the
        # container listens on IPv4 only, so every connection waited 5 s for a timeout.
        return (
            f"postgresql://{self.postgres_user}:{password}"
            f"@127.0.0.1:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The one shared Settings object. Tests build their own `Settings(...)` instead."""
    return Settings()
