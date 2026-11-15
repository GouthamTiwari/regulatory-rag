"""The one place that creates the boto3 `bedrock-runtime` client."""

import os
from typing import Literal

import boto3
from botocore.config import Config

from regrag.config import Settings, get_settings

AuthMode = Literal["api_key", "iam"]

BEARER_ENV_VAR = "AWS_BEARER_TOKEN_BEDROCK"

# Adaptive retries back off automatically when Bedrock throttles us (HTTP 429), which
# happens easily on a new account's default quotas.
_CLIENT_CONFIG = Config(
    retries={"max_attempts": 6, "mode": "adaptive"},
    connect_timeout=10,
    read_timeout=120,  # an LLM answer can take a while; embeddings and rerank are fast
)

_clients: dict[tuple[str, AuthMode], object] = {}


class BedrockAuthError(RuntimeError):
    """Credentials are missing or ambiguous. Messages name env vars, never their values."""


def auth_mode(settings: Settings) -> AuthMode:
    """Decide which of the two auth options from SPEC 2.3 is configured."""
    token = settings.aws_bearer_token_bedrock.get_secret_value().strip()
    key_id = settings.aws_access_key_id.get_secret_value().strip()
    secret = settings.aws_secret_access_key.get_secret_value().strip()

    if token and (key_id or secret):
        # Why refuse instead of picking one: a beginner can't tell which one is in use,
        # and an unexpected IAM key may have far wider permissions than intended.
        raise BedrockAuthError(
            f"Both {BEARER_ENV_VAR} and AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY are set in "
            ".env. Keep only one auth option."
        )
    if token:
        return "api_key"
    if key_id and secret:
        return "iam"
    if key_id or secret:
        raise BedrockAuthError(
            "Option B needs both AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env."
        )
    raise BedrockAuthError(
        f"No Bedrock credentials found. Set {BEARER_ENV_VAR} (recommended: a Bedrock API "
        "key) or AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY in .env."
    )


def get_runtime_client(settings: Settings | None = None, *, region: str | None = None):
    """A cached `bedrock-runtime` client for one region (default: settings.aws_region).

    The reranker passes `region=settings.bedrock_rerank_region`, because Mumbai has no
    Bedrock reranker. A long-term Bedrock API key works in every region, so one key serves both.
    """
    settings = settings or get_settings()
    region = region or settings.aws_region
    mode = auth_mode(settings)
    cache_key = (region, mode)
    if cache_key in _clients:
        return _clients[cache_key]

    if mode == "api_key":
        # boto3 reads the API key only from the process environment, so make sure the
        # value from Settings is the one there.
        os.environ[BEARER_ENV_VAR] = settings.aws_bearer_token_bedrock.get_secret_value().strip()
        client = boto3.client("bedrock-runtime", region_name=region, config=_CLIENT_CONFIG)
    else:
        # Why remove it: botocore treats an *empty* AWS_BEARER_TOKEN_BEDROCK (which an
        # unfilled .env line creates) as "a token exists" and would send an empty key.
        if not os.environ.get(BEARER_ENV_VAR, "").strip():
            os.environ.pop(BEARER_ENV_VAR, None)
        client = boto3.client(
            "bedrock-runtime",
            region_name=region,
            aws_access_key_id=settings.aws_access_key_id.get_secret_value().strip(),
            aws_secret_access_key=settings.aws_secret_access_key.get_secret_value().strip(),
            config=_CLIENT_CONFIG,
        )
    _clients[cache_key] = client
    return client


def clear_client_cache() -> None:
    """Forget cached clients (tests, or after changing .env in a long-running process)."""
    _clients.clear()
