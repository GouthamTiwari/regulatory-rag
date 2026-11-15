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

# The answering model is reached through a global cross-region inference profile: the base
# model ID has no in-region on-demand option, and `global.` is the cheapest prefix (SPEC 2.1).
HAIKU_PROFILE_ID = "global.anthropic.claude-haiku-5-5"


class Settings(BaseSettings):
    # env_ignore_empty: `.env.example` copied as-is has `NAME=` lines; an empty value must
    # mean "use the default", not "set this to an empty string".
    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)

    # --- AWS region and auth (SPEC 2.2, 2.3) -------------------------------------------
    # Tokyo is the nearest region to India with Titan V2, a reranker and Haiku 5.5.
    aws_region: str = "ap-northeast-1"
    # Option A, recommended: a Bedrock-only API key that expires on its own.
    aws_bearer_token_bedrock: SecretStr = SecretStr("")
    # Option B: IAM user access keys. Set only one option.
    aws_access_key_id: SecretStr = SecretStr("")
    aws_secret_access_key: SecretStr = SecretStr("")

    # --- Bedrock model IDs (SPEC 2.1) ---------------------------------------------------
    # 1024-dim embeddings, in-region, $0.02 per 1M tokens.
    bedrock_embed_model_id: str = "amazon.titan-embed-text-v2:0"
    # Called via InvokeModel because Bedrock API keys can't use the agent-runtime Rerank API.
    bedrock_rerank_model_id: str = "cohere.rerank-v3-5:0"
    # Router and answer model: cheap and fast enough to call twice per question.
    bedrock_llm_model_id: str = HAIKU_PROFILE_ID
    # Faithfulness judge: Haiku for development runs; Task 28 uses Sonnet 5.5 for the final run.
    bedrock_judge_model_id: str = HAIKU_PROFILE_ID

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
    # Below this top rerank score we abstain. A starting guess; Task 28 picks the real value.
    abstain_threshold: float = Field(default=0.30, ge=0, le=1)
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
        return (
            f"postgresql://{self.postgres_user}:{password}"
            f"@localhost:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The one shared Settings object. Tests build their own `Settings(...)` instead."""
    return Settings()
