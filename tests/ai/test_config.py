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
    OpenRouterClient,
    aclose,
    client_from_env,
    settings,
    shared_client,
    startup,
)
from pcn_clone.ai.config import (
    DEFAULT_MODEL,
    AiSettings,
    environment,
    load_settings,
    parse_dotenv,
)
from tests.ai.conftest import SetAiEnvironment


def test_defaults() -> None:
    assert load_settings({}) == AiSettings(
        openrouter_api_key=None,
        openrouter_model=DEFAULT_MODEL,
        provider="openrouter",
        timeout_seconds=600.0,
        max_retries=2,
        provider_order=(),
        fake_delay_seconds=0.0,
        fake_fail=frozenset(),
    )
    assert DEFAULT_MODEL == "openai/gpt-5.6-luna"


def test_every_variable() -> None:
    settings = load_settings(
        {
            "OPENROUTER_API_KEY": " sk-test ",
            "OPENROUTER_MODEL": "openai/gpt-x",
            "PCN_AI_PROVIDER": "Fake",
            "PCN_AI_TIMEOUT_SECONDS": "30.5",
            "PCN_AI_MAX_RETRIES": "5",
            "PCN_AI_PROVIDER_ORDER": "openai, azure,,",
            "PCN_AI_FAKE_DELAY_SECONDS": "0",
            "PCN_AI_FAKE_FAIL": "project_title, objectives",
        }
    )
    assert settings == AiSettings(
        openrouter_api_key="sk-test",
        openrouter_model="openai/gpt-x",
        provider="fake",
        timeout_seconds=30.5,
        max_retries=5,
        provider_order=("openai", "azure"),
        fake_delay_seconds=0.0,
        fake_fail=frozenset({"project_title", "objectives"}),
    )


def test_blank_values_fall_back() -> None:
    settings = load_settings(
        {
            "OPENROUTER_API_KEY": "",
            "OPENROUTER_MODEL": " ",
            "PCN_AI_TIMEOUT_SECONDS": "",
        }
    )
    assert settings.openrouter_api_key is None
    assert settings.openrouter_model == DEFAULT_MODEL
    assert settings.timeout_seconds == 600.0


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("PCN_AI_PROVIDER", "openai", '"openrouter" or "fake"'),
        ("PCN_AI_TIMEOUT_SECONDS", "soon", "must be a number"),
        ("PCN_AI_TIMEOUT_SECONDS", "0", "finite number > 0"),
        ("PCN_AI_TIMEOUT_SECONDS", "-1", "finite number > 0"),
        ("PCN_AI_TIMEOUT_SECONDS", "inf", "finite number > 0"),
        ("PCN_AI_MAX_RETRIES", "1.5", "whole number from 0 to 5"),
        ("PCN_AI_MAX_RETRIES", "6", "whole number from 0 to 5"),
        ("PCN_AI_MAX_RETRIES", "-1", "whole number from 0 to 5"),
        ("PCN_AI_FAKE_DELAY_SECONDS", "nan", "finite number >= 0"),
    ],
)
def test_malformed_values_name_the_variable(
    name: str, value: str, message: str
) -> None:
    with pytest.raises(AiConfigurationError, match=f"{name} must be") as raised:
        load_settings({name: value})
    assert message in str(raised.value)


def test_api_key_is_not_in_repr() -> None:
    settings = AiSettings(openrouter_api_key="sk-or-secret-123")
    assert "sk-or-secret-123" not in repr(settings)
    assert "sk-or-secret-123" not in repr(OpenRouterClient(api_key="sk-or-secret-123"))


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
            openrouter_api_key="sk",
            openrouter_model="openai/gpt-x",
            timeout_seconds=12.0,
            max_retries=4,
            provider_order=("openai",),
        )
    )
    assert isinstance(real, OpenRouterClient)
    assert real.model == "openai/gpt-x"
    assert real.timeout_seconds == 12.0
    assert real.max_retries == 4
    assert real.provider_order == ("openai",)
    assert real.deadline_seconds == 60.0


def test_openrouter_requires_a_key() -> None:
    with pytest.raises(AiConfigurationError, match="OPENROUTER_API_KEY is not set"):
        client_from_env(AiSettings(provider="openrouter"))


def test_startup_fails_fast_without_a_key(ai_env: SetAiEnvironment) -> None:
    ai_env(PCN_AI_PROVIDER="openrouter")
    with pytest.raises(AiConfigurationError, match="OPENROUTER_API_KEY"):
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


def test_startup_is_quiet_with_a_key(
    ai_env: SetAiEnvironment, caplog: pytest.LogCaptureFixture
) -> None:
    ai_env(OPENROUTER_API_KEY="sk-test")
    with caplog.at_level(logging.WARNING, logger="pcn_clone.ai.provider"):
        startup()
    assert caplog.text == ""
    assert isinstance(shared_client(), OpenRouterClient)
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
