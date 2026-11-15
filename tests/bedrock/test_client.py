"""Bedrock client: auth option detection, clear errors, no secret leaks. No AWS calls."""

import os

import pytest

from regrag.bedrock import client as client_module
from regrag.bedrock.client import (
    BEARER_ENV_VAR,
    BedrockAuthError,
    auth_mode,
    clear_client_cache,
    get_runtime_client,
)
from regrag.config import Settings

FAKE_TOKEN = "TEST-bedrock-api-key-not-real"
FAKE_KEY_ID = "TESTKEYID-not-real"
FAKE_SECRET = "TEST-secret-not-real"


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """No real credentials from the machine, a fresh cache, and boto3 replaced by a spy."""
    # setenv first so monkeypatch remembers the original value and restores it afterwards,
    # even though get_runtime_client() writes os.environ itself.
    monkeypatch.setenv(BEARER_ENV_VAR, "placeholder")
    monkeypatch.delenv(BEARER_ENV_VAR)
    # A developer's .env may set these; tests must see the code defaults.
    for name in (
        "AWS_REGION",
        "BEDROCK_RERANK_REGION",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    clear_client_cache()
    calls = []

    def fake_client(service, **kwargs):
        calls.append((service, kwargs))
        return object()

    monkeypatch.setattr(client_module.boto3, "client", fake_client)
    yield calls
    clear_client_cache()


def test_no_credentials_gives_clear_error():
    with pytest.raises(BedrockAuthError) as info:
        auth_mode(Settings())
    message = str(info.value)
    assert BEARER_ENV_VAR in message
    assert "AWS_ACCESS_KEY_ID" in message


def test_both_options_set_is_refused_without_leaking_values():
    s = Settings(
        aws_bearer_token_bedrock=FAKE_TOKEN,
        aws_access_key_id=FAKE_KEY_ID,
        aws_secret_access_key=FAKE_SECRET,
    )
    with pytest.raises(BedrockAuthError) as info:
        auth_mode(s)
    for secret in (FAKE_TOKEN, FAKE_KEY_ID, FAKE_SECRET):
        assert secret not in str(info.value)


def test_half_an_iam_key_is_refused():
    with pytest.raises(BedrockAuthError):
        auth_mode(Settings(aws_access_key_id=FAKE_KEY_ID))


def test_whitespace_only_token_counts_as_missing():
    with pytest.raises(BedrockAuthError):
        auth_mode(Settings(aws_bearer_token_bedrock="   "))


def test_api_key_mode_puts_token_in_env_and_uses_region(isolated):
    s = Settings(aws_bearer_token_bedrock=FAKE_TOKEN, aws_region="ap-northeast-1")
    get_runtime_client(s)
    service, kwargs = isolated[0]
    assert service == "bedrock-runtime"
    assert kwargs["region_name"] == "ap-northeast-1"
    assert "aws_access_key_id" not in kwargs  # bearer auth, not IAM keys
    assert os.environ[BEARER_ENV_VAR] == FAKE_TOKEN


def test_iam_mode_passes_keys_and_drops_empty_bearer_var(isolated, monkeypatch):
    # An unfilled `.env` line leaves an empty variable; botocore would treat it as a token.
    monkeypatch.setenv(BEARER_ENV_VAR, "")
    s = Settings(aws_access_key_id=FAKE_KEY_ID, aws_secret_access_key=FAKE_SECRET)
    get_runtime_client(s)
    _, kwargs = isolated[0]
    assert kwargs["aws_access_key_id"] == FAKE_KEY_ID
    assert kwargs["aws_secret_access_key"] == FAKE_SECRET
    assert BEARER_ENV_VAR not in os.environ


def test_client_is_cached_per_region_and_mode(isolated):
    s = Settings(aws_bearer_token_bedrock=FAKE_TOKEN)
    first = get_runtime_client(s)
    assert get_runtime_client(s) is first
    assert len(isolated) == 1
    get_runtime_client(Settings(aws_bearer_token_bedrock=FAKE_TOKEN, aws_region="us-east-1"))
    assert len(isolated) == 2


def test_region_override_for_the_reranker(isolated):
    s = Settings(aws_bearer_token_bedrock=FAKE_TOKEN)
    main = get_runtime_client(s)
    rerank = get_runtime_client(s, region=s.bedrock_rerank_region)
    assert main is not rerank
    assert [kw["region_name"] for _, kw in isolated] == ["ap-south-1", "ap-northeast-1"]


def test_adaptive_retries_are_configured(isolated):
    get_runtime_client(Settings(aws_bearer_token_bedrock=FAKE_TOKEN))
    config = isolated[0][1]["config"]
    assert config.retries["mode"] == "adaptive"
