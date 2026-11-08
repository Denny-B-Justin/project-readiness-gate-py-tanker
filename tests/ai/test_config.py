"""Settings come from the environment over an optional ``.env`` file, and
select the model client."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from pcn_clone.ai import (
    AiConfigurationError,
    FakeClient,
    MaiClient,
    aclose,
    client_from_env,
    settings,
    shared_client,
    startup,
)
from pcn_clone.ai.config import (
    AiSettings,
    environment,
    load_settings,
    parse_dotenv,
)
from tests.ai.conftest import SetAiEnvironment

GATEWAY = "https://gateway.example.invalid/posit-mai/conversationalai/"
GPT_ENDPOINT = "https://mai.example.invalid/maifactory/openai/responses"
GEMINI_ENDPOINT = "https://mai.example.invalid/maifactory/gemini/interactions"
GUID = "0b7e3a52-6c1d-4f7e-9a0b-2f5d8c4e1a93"
MAI = {
    "MAI_BASE_URL": GATEWAY,
    "MAI_ENDPOINT": GPT_ENDPOINT,
    "CONNECT_CONTENT_GUID": GUID,
}


def test_defaults() -> None:
    assert load_settings({}) == AiSettings(
        provider="WB-mAI",
        mai_base_url=None,
        mai_endpoint=None,
        mai_model=None,
        connect_content_guid=None,
        timeout_seconds=600.0,
        max_retries=2,
        max_output_tokens=None,
        fake_delay_seconds=0.0,
        fake_fail=frozenset(),
    )


def test_every_variable() -> None:
    settings = load_settings(
        {
            "PCN_AI_PROVIDER": "Fake",
            "MAI_BASE_URL": f" {GATEWAY.rstrip('/')} ",
            "MAI_ENDPOINT": GEMINI_ENDPOINT,
            "MAI_MODEL": "gemini-3.6-flash",
            "CONNECT_CONTENT_GUID": GUID,
            "PCN_AI_TIMEOUT_SECONDS": "30.5",
            "PCN_AI_MAX_RETRIES": "5",
            "PCN_AI_MAX_OUTPUT_TOKENS": "4000",
            "PCN_AI_FAKE_DELAY_SECONDS": "0",
            "PCN_AI_FAKE_FAIL": "project_title, objectives,,",
        }
    )
    assert settings == AiSettings(
        provider="fake",
        mai_base_url=GATEWAY,
        mai_endpoint=GEMINI_ENDPOINT,
        mai_model="gemini-3.6-flash",
        connect_content_guid=GUID,
        timeout_seconds=30.5,
        max_retries=5,
        max_output_tokens=4000,
        fake_delay_seconds=0.0,
        fake_fail=frozenset({"project_title", "objectives"}),
    )


@pytest.mark.parametrize("value", ["WB-mAI", "wb-mai", "WB-MAI", " wb-Mai "])
def test_provider_is_case_insensitive(value: str) -> None:
    assert load_settings({"PCN_AI_PROVIDER": value}).provider == "WB-mAI"
    assert load_settings({"PCN_AI_PROVIDER": "FAKE"}).provider == "fake"


def test_base_url_gets_a_trailing_slash() -> None:
    plain = "http://127.0.0.1:9000/posit-mai/conversationalai"
    assert load_settings({"MAI_BASE_URL": plain}).mai_base_url == f"{plain}/"
    assert load_settings({"MAI_BASE_URL": f"{plain}/"}).mai_base_url == f"{plain}/"


def test_blank_values_fall_back() -> None:
    settings = load_settings(
        {
            "PCN_AI_PROVIDER": " ",
            "MAI_BASE_URL": "",
            "MAI_ENDPOINT": " ",
            "MAI_MODEL": "",
            "CONNECT_CONTENT_GUID": "",
            "PCN_AI_TIMEOUT_SECONDS": "",
            "PCN_AI_MAX_OUTPUT_TOKENS": "",
        }
    )
    assert settings == AiSettings()


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("PCN_AI_PROVIDER", "openai", '"WB-mAI" or "fake"'),
        ("MAI_BASE_URL", "gateway.example.invalid/posit-mai/", "http:// or https://"),
        ("MAI_BASE_URL", "ftp://gateway.example.invalid/", "http:// or https://"),
        ("PCN_AI_TIMEOUT_SECONDS", "soon", "must be a number"),
        ("PCN_AI_TIMEOUT_SECONDS", "0", "finite number > 0"),
        ("PCN_AI_TIMEOUT_SECONDS", "-1", "finite number > 0"),
        ("PCN_AI_TIMEOUT_SECONDS", "inf", "finite number > 0"),
        ("PCN_AI_MAX_RETRIES", "1.5", "whole number from 0 to 5"),
        ("PCN_AI_MAX_RETRIES", "6", "whole number from 0 to 5"),
        ("PCN_AI_MAX_RETRIES", "-1", "whole number from 0 to 5"),
        ("PCN_AI_MAX_OUTPUT_TOKENS", "0", "positive whole number"),
        ("PCN_AI_MAX_OUTPUT_TOKENS", "lots", "positive whole number"),
        ("PCN_AI_FAKE_DELAY_SECONDS", "nan", "finite number >= 0"),
    ],
)
def test_malformed_values_name_the_variable(
    name: str, value: str, message: str
) -> None:
    with pytest.raises(AiConfigurationError, match=f"{name} must be") as raised:
        load_settings({name: value})
    assert message in str(raised.value)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("KEY=v", {"KEY": "v"}),
        ("KEY = v ", {"KEY": "v"}),
        ("KEY=v # comment", {"KEY": "v"}),
        ("KEY=v\t# comment", {"KEY": "v"}),
        ("KEY=v#not-a-comment", {"KEY": "v#not-a-comment"}),
        ('KEY="v" # comment', {"KEY": "v"}),
        ("KEY='a # b'", {"KEY": "a # b"}),
        ('KEY="openai/gpt # quoted"', {"KEY": "openai/gpt # quoted"}),
        ('KEY="unterminated', {"KEY": '"unterminated'}),
        ("export KEY=v", {"KEY": "v"}),
        ("export\tKEY=v", {"KEY": "v"}),
        ("﻿KEY=v", {"KEY": "v"}),
        ("# comment\n\nnot a pair\nA=1\nB=2", {"A": "1", "B": "2"}),
        ("KEY=", {"KEY": ""}),
    ],
)
def test_parse_dotenv(text: str, expected: dict[str, str]) -> None:
    assert parse_dotenv(text) == expected


def test_environment_prefers_process_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_bytes("﻿PCN_AI_PROVIDER=fake\nPCN_AI_MAX_RETRIES=5\n".encode())
    monkeypatch.setenv("PCN_AI_MAX_RETRIES", "1")
    monkeypatch.delenv("PCN_AI_PROVIDER", raising=False)
    merged = environment(dotenv)
    assert merged["PCN_AI_PROVIDER"] == "fake"
    assert merged["PCN_AI_MAX_RETRIES"] == "1"
    assert "PCN_AI_PROVIDER" not in environment(tmp_path / "missing.env")


def test_settings_are_cached_until_reset(ai_env: SetAiEnvironment) -> None:
    ai_env(PCN_AI_PROVIDER="fake", PCN_AI_FAKE_DELAY_SECONDS="0.5")
    first = settings()
    assert first.fake_delay_seconds == 0.5
    ai_env(PCN_AI_PROVIDER="fake")
    assert settings().fake_delay_seconds == 0.0
    assert settings() is settings()


def test_client_from_env_selects_provider() -> None:
    fake = client_from_env(
        AiSettings(provider="fake", fake_delay_seconds=0.5, fake_fail=frozenset({"*"}))
    )
    assert isinstance(fake, FakeClient)
    assert fake.delay_seconds == 0.5
    assert fake.fail == frozenset({"*"})

    real = client_from_env(
        AiSettings(
            mai_base_url=GATEWAY,
            mai_endpoint=GPT_ENDPOINT,
            mai_model="gpt-6-luna",
            connect_content_guid=GUID,
            timeout_seconds=12.0,
            max_retries=4,
            max_output_tokens=2000,
        )
    )
    assert isinstance(real, MaiClient)
    assert real.family == "gpt"
    assert real.model == "gpt-6-luna"
    assert real.connection.base_url == GATEWAY
    assert real.query == {"mai-endpoint": GPT_ENDPOINT}
    assert real.headers == {"X-Posit-App-Id": GUID, "x-source-type": "interactive"}
    assert real.timeout_seconds == 12.0
    assert real.max_retries == 4
    assert real.max_output_tokens == 2000
    assert real.deadline_seconds == 60.0
    assert repr(real) == "MaiClient(family='gpt', model='gpt-6-luna')"


def test_mai_requires_its_settings() -> None:
    with pytest.raises(AiConfigurationError, match="MAI_BASE_URL is not set"):
        client_from_env(AiSettings())


def _without(name: str) -> dict[str, str]:
    return {key: value for key, value in MAI.items() if key != name}


@pytest.mark.parametrize(
    ("variables", "message"),
    [
        pytest.param(_without("MAI_BASE_URL"), "MAI_BASE_URL is not set", id="url"),
        pytest.param(
            _without("MAI_ENDPOINT"), "MAI_ENDPOINT is not set", id="endpoint"
        ),
        pytest.param(
            _without("CONNECT_CONTENT_GUID"),
            "CONNECT_CONTENT_GUID is not set: the mAI Gateway only answers apps "
            "running on Posit Connect",
            id="not-on-connect",
        ),
        pytest.param(
            {**MAI, "MAI_MODEL": "claude-haiku-5-5"},
            "MAI_MODEL is a Claude model but MAI_ENDPOINT is a GPT endpoint",
            id="family-mismatch",
        ),
        pytest.param(
            {**MAI, "MAI_ENDPOINT": "https://mai.example.invalid/unknown"},
            "MAI_ENDPOINT is not a GPT",
            id="unknown-family",
        ),
        pytest.param(
            {**MAI, "PCN_AI_PROVIDER": "openai"},
            'PCN_AI_PROVIDER must be "WB-mAI" or "fake"',
            id="bad-provider",
        ),
    ],
)
def test_startup_fails_fast_on_incomplete_mai_settings(
    ai_env: SetAiEnvironment, variables: dict[str, str], message: str
) -> None:
    ai_env(**variables)
    with pytest.raises(AiConfigurationError, match=message):
        startup()


def test_startup_fails_fast_on_malformed_settings(ai_env: SetAiEnvironment) -> None:
    ai_env(PCN_AI_PROVIDER="fake", PCN_AI_MAX_RETRIES="lots")
    with pytest.raises(AiConfigurationError, match="PCN_AI_MAX_RETRIES"):
        startup()


def test_startup_warns_when_fake(
    ai_env: SetAiEnvironment, caplog: pytest.LogCaptureFixture
) -> None:
    ai_env(PCN_AI_PROVIDER="fake")
    with caplog.at_level(logging.WARNING, logger="pcn_clone.ai.provider"):
        startup()
    assert "PCN_AI_PROVIDER=fake" in caplog.text


def test_startup_logs_provider_family_and_model(
    ai_env: SetAiEnvironment, caplog: pytest.LogCaptureFixture
) -> None:
    ai_env(**MAI)
    with caplog.at_level(logging.INFO, logger="pcn_clone.ai.provider"):
        startup()
    [record] = caplog.records
    assert record.levelno == logging.INFO
    assert record.getMessage() == "AI provider WB-mAI: gpt family, model gpt-5.6-luna"
    assert "http" not in caplog.text
    assert isinstance(shared_client(), MaiClient)
    asyncio.run(aclose())


def test_shared_client_follows_the_settings(ai_env: SetAiEnvironment) -> None:
    ai_env(PCN_AI_PROVIDER="fake")
    first = shared_client()
    assert shared_client() is first
    ai_env(PCN_AI_PROVIDER="fake", PCN_AI_FAKE_FAIL="*")
    second = shared_client()
    assert second is not first
    assert isinstance(second, FakeClient)
    assert second.fail == frozenset({"*"})
    asyncio.run(aclose())
    assert shared_client() is not second
