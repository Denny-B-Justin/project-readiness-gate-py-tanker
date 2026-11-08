"""A one-off check of the Posit mAI Gateway from the deployed app.

The gateway only answers apps running on Posit Connect, so the client is
proven there: this script resolves the configured provider, model family
and model, then makes one small real call per output contract
(``field_evaluation``, ``assessment_finding`` and ``mca_score_finding``)
through the app's own entry points on the sample project, and reports for
each whether it passed, how long it took, the schema compatibility level it
settled at and, on failure, the gateway's error as the app logs it
(sanitised: no prompts, replies or request bodies).

Wherever the app's Connect environment applies (the ``MAI_*`` variables,
and ``CONNECT_CONTENT_GUID`` set by Connect), from the project root::

    python -m tests.ai.live_check

Against the local fake gateway, to test the script itself::

    python -m tests.ai.live_check --fake --family claude

The exit status is 0 when every check passes, 1 when one fails and 2 when
the settings are unusable. pytest does not collect this module; the
``live``-marked ``tests/ai/test_live.py`` is the one-call pytest variant.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pcn_clone.ai import (
    AiConfigurationError,
    MaiClient,
    assess_dimension,
    build_snapshot,
    evaluate_field,
    reset_settings,
    score_criterion,
    settings,
    shared_client,
)
from pcn_clone.ai.config import MAI_PROVIDER
from pcn_clone.content import load_assessment, load_default_project, load_mca
from tests.ai.fake_gateway import FAMILIES, FakeGateway, Family
from tests.ai.support import default_answer, section_of

FAKE_ENDPOINTS: dict[Family, str] = {
    "gpt": "https://mai.example.invalid/maifactory/openai/responses",
    "gemini": "https://mai.example.invalid/maifactory/gemini/interactions",
    "claude": (
        "https://mai.example.invalid/maifactory/bedrock/model/"
        "us.anthropic.<model>/converse"
    ),
}
FAKE_APP_ID = "00000000-0000-0000-0000-000000000000"
FIELD_ID = "project_title"


@dataclass(frozen=True, slots=True)
class Outcome:
    """One contract's result."""

    contract: str
    ok: bool
    seconds: float
    schema_level: int
    model: str | None
    error: str | None


def _pins() -> dict[str, Any]:
    snapshot = build_snapshot(load_default_project().submission).to_json()
    return {
        key: snapshot[key]
        for key in (
            "templateId",
            "templateVersion",
            "model",
            "assessmentInputDigest",
            "submission",
        )
    }


async def _field_evaluation(client: MaiClient) -> tuple[bool, str | None, str | None]:
    response = await evaluate_field(
        section_of(FIELD_ID), FIELD_ID, default_answer(FIELD_ID), client=client
    )
    return response.ok, response.model, response.error_message


async def _assessment_finding(client: MaiClient) -> tuple[bool, str | None, str | None]:
    snapshot = build_snapshot(load_default_project().submission)
    response = await assess_dimension(
        {
            **_pins(),
            "assessmentSetId": snapshot.assessment_set_id,
            "assessmentSetVersion": snapshot.assessment_set_version,
            "dimensionId": load_assessment().dimensions[0].id,
        },
        client=client,
    )
    model = response.finding.model if response.finding is not None else None
    return response.ok, model, response.error_message


async def _mca_score_finding(client: MaiClient) -> tuple[bool, str | None, str | None]:
    snapshot = build_snapshot(load_default_project().submission)
    response = await score_criterion(
        {
            **_pins(),
            "mcaSetId": snapshot.mca_set_id,
            "mcaSetVersion": snapshot.mca_set_version,
            "criterionId": load_mca().matrix.criteria[0].id,
        },
        client=client,
    )
    model = response.finding.model if response.finding is not None else None
    return response.ok, model, response.error_message


CHECKS: tuple[
    tuple[str, Callable[[MaiClient], Awaitable[tuple[bool, str | None, str | None]]]],
    ...,
] = (
    ("field_evaluation", _field_evaluation),
    ("assessment_finding", _assessment_finding),
    ("mca_score_finding", _mca_score_finding),
)


async def run_checks(client: MaiClient) -> list[Outcome]:
    """Run the checks one after another, so each schema level is the one
    that call settled at."""
    outcomes: list[Outcome] = []
    try:
        for contract, check in CHECKS:
            print(f"- {contract} ...", flush=True)
            started = time.perf_counter()
            ok, model, error = await check(client)
            outcomes.append(
                Outcome(
                    contract=contract,
                    ok=ok,
                    seconds=time.perf_counter() - started,
                    schema_level=client.schema_level,
                    model=model,
                    error=error,
                )
            )
    finally:
        await client.aclose()
    return outcomes


def _use_fake_gateway(family: Family) -> FakeGateway:
    gateway = FakeGateway(family).start()
    os.environ.update(
        {
            "PCN_AI_PROVIDER": MAI_PROVIDER,
            "MAI_BASE_URL": gateway.url,
            "MAI_ENDPOINT": FAKE_ENDPOINTS[family],
            "CONNECT_CONTENT_GUID": FAKE_APP_ID,
        }
    )
    os.environ.pop("MAI_MODEL", None)
    return gateway


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--fake", action="store_true", help="run against the local fake gateway"
    )
    parser.add_argument("--family", choices=FAMILIES, default="gpt")
    options = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING, format="    %(levelname)s %(name)s: %(message)s"
    )

    gateway = _use_fake_gateway(options.family) if options.fake else None
    reset_settings()
    try:
        try:
            config = settings()
            client = shared_client()
        except AiConfigurationError as error:
            print(f"Settings unusable: {error}")
            return 2
        if config.provider != MAI_PROVIDER or not isinstance(client, MaiClient):
            print(f"PCN_AI_PROVIDER is {config.provider}; set it to {MAI_PROVIDER}.")
            return 2
        print(
            f"Provider {MAI_PROVIDER}, family {client.family}, model {client.model}"
            + (" (local fake gateway)" if gateway is not None else "")
        )
        outcomes = asyncio.run(run_checks(client))
    finally:
        if gateway is not None:
            gateway.close()

    print()
    for outcome in outcomes:
        status = "PASS" if outcome.ok else "FAIL"
        line = (
            f"{status}  {outcome.contract:<20} {outcome.seconds:6.1f} s  "
            f"schema level {outcome.schema_level}"
        )
        if outcome.ok:
            line += f"  model {outcome.model}"
        else:
            line += f"  {outcome.error}"
        print(line)
    if not all(outcome.ok for outcome in outcomes):
        print("\nThe gateway's own error for each failure is logged above.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
