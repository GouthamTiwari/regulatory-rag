"""Settings: safe defaults, empty values fall back, secrets never leak into repr/logs."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from regrag.config import NOVA_LITE_PROFILE_ID, NOVA_PRO_PROFILE_ID, Settings

REPO_ROOT = Path(__file__).resolve().parent.parent

# Every variable a developer's .env might set. Cleared in tests so a real .env on the
# machine cannot change the results (or leak a real key into test output).
ENV_VARS = [
    "AWS_REGION",
    "AWS_BEARER_TOKEN_BEDROCK",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "BEDROCK_EMBED_MODEL_ID",
    "BEDROCK_RERANK_MODEL_ID",
    "BEDROCK_LLM_MODEL_ID",
    "BEDROCK_JUDGE_MODEL_ID",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "POSTGRES_PORT",
    "DATABASE_URL",
    "RERANK_TOP_N",
]


@pytest.fixture
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_import_without_env_file_does_not_crash(tmp_path):
    # Fresh interpreter, empty working directory, none of our variables set.
    env = {k: v for k, v in os.environ.items() if k not in ENV_VARS}
    result = subprocess.run(
        [sys.executable, "-c", "import regrag.config as c; print(c.get_settings().aws_region)"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_defaults_without_env(clean_env):
    s = Settings()
    assert s.aws_region == "ap-northeast-1"
    assert s.aws_bearer_token_bedrock.get_secret_value() == ""
    assert s.aws_secret_access_key.get_secret_value() == ""
    assert s.bedrock_llm_model_id == NOVA_LITE_PROFILE_ID
    assert s.postgres_port == 5433


def test_empty_values_fall_back_to_defaults(clean_env):
    # This is what a copied, unfilled .env.example looks like.
    clean_env.setenv("BEDROCK_JUDGE_MODEL_ID", "")
    clean_env.setenv("AWS_REGION", "")
    clean_env.setenv("POSTGRES_PORT", "")
    s = Settings()
    assert s.bedrock_judge_model_id == NOVA_LITE_PROFILE_ID
    assert s.aws_region == "ap-northeast-1"
    assert s.postgres_port == 5433


def test_env_overrides_defaults(clean_env):
    clean_env.setenv("BEDROCK_JUDGE_MODEL_ID", NOVA_PRO_PROFILE_ID)
    clean_env.setenv("RERANK_TOP_N", "6")
    s = Settings()
    assert s.bedrock_judge_model_id == NOVA_PRO_PROFILE_ID
    assert s.rerank_top_n == 6


def test_secrets_are_masked_in_repr_and_str(clean_env):
    token = "TEST-bearer-token-not-real-123"
    clean_env.setenv("AWS_BEARER_TOKEN_BEDROCK", token)
    clean_env.setenv("POSTGRES_PASSWORD", "test-db-password")
    s = Settings()
    for text in (repr(s), str(s), repr(s.model_dump())):
        assert token not in text
        assert "test-db-password" not in text
    # The real value is still available to code that deliberately asks for it.
    assert s.aws_bearer_token_bedrock.get_secret_value() == token


def test_database_dsn_built_from_parts(clean_env):
    s = Settings(postgres_password="pw", postgres_port=5433)
    assert s.database_dsn() == "postgresql://regrag:pw@127.0.0.1:5433/regrag"


def test_database_url_wins_when_set(clean_env):
    s = Settings(database_url="postgresql://u:p@db:5432/x")
    assert s.database_dsn() == "postgresql://u:p@db:5432/x"


def test_invariants_hold_for_defaults(clean_env):
    # Checked as relationships, not exact numbers, so Task 28 can tune values freely.
    s = Settings()
    assert s.chunk_overlap_tokens < s.chunk_target_tokens <= s.chunk_max_tokens
    assert s.rerank_top_n <= s.fused_top_k
    assert 0 <= s.abstain_threshold <= 1
    assert "rbi.org.in" in s.allowed_download_hosts
    assert "gstcouncil.gov.in" in s.allowed_download_hosts


@pytest.mark.parametrize(
    "overrides",
    [
        {"chunk_overlap_tokens": 400},  # overlap as big as the chunk
        {"chunk_target_tokens": 600},  # target above the hard max
        {"rerank_top_n": 50},  # keep more than we retrieved
        {"abstain_threshold": 1.5},  # scores are 0..1
        {"postgres_port": 0},
    ],
)
def test_bad_values_fail_loudly(clean_env, overrides):
    with pytest.raises(ValidationError):
        Settings(**overrides)
