"""The AI layer: prompts, structured-output schemas, model clients, the
single-field evaluation entry point and the reviewer-side assessment and
scoring entry points.

The form calls :func:`evaluate_field` (async, never raises) and the
synchronous :func:`readiness` / :func:`is_field_ready` checks. The reviewer
workspace freezes a submission with :func:`build_snapshot` at Submit, then
calls :func:`assess_dimension` per dimension and :func:`score_criterion` per
MCA criterion (async, never raise). Calls share
one process-wide model client chosen by the environment
(:func:`settings`; ``PCN_AI_PROVIDER=fake`` selects the offline
:class:`FakeClient`) unless a client is passed explicitly. The app calls
:func:`startup` when it is built, so a misconfiguration stops it there, and
awaits :func:`aclose` at shutdown; :func:`reset_settings` makes the next call
read the environment again.
"""

from pcn_clone.ai.assess import (
    ASSESSMENT_ERROR_MESSAGE,
    SCORING_ERROR_MESSAGE,
    AssessDimensionRequest,
    AssessDimensionResponse,
    DimensionFinding,
    ErrorCode,
    ErrorKind,
    IntakeSnapshot,
    RunError,
    ScoreCriterionRequest,
    ScoreCriterionResponse,
    ScoreFinding,
    VerifiedCitation,
    assess_dimension,
    build_snapshot,
    score_criterion,
)
from pcn_clone.ai.config import (
    AiConfigurationError,
    AiSettings,
    reset_settings,
    settings,
)
from pcn_clone.ai.evaluate import (
    ENGINE_ERROR_MESSAGE,
    NOT_CONFIGURED_MESSAGE,
    FieldEvaluationResponse,
    evaluate_field,
    is_field_ready,
    readiness,
)
from pcn_clone.ai.provider import (
    FakeClient,
    ModelClient,
    ModelReply,
    OpenRouterClient,
    ProviderError,
    TokenUsage,
    aclose,
    client_from_env,
    shared_client,
    startup,
)
from pcn_clone.ai.schemas import FieldEvaluation, Verdict

__all__ = [
    "ASSESSMENT_ERROR_MESSAGE",
    "ENGINE_ERROR_MESSAGE",
    "NOT_CONFIGURED_MESSAGE",
    "SCORING_ERROR_MESSAGE",
    "AiConfigurationError",
    "AiSettings",
    "AssessDimensionRequest",
    "AssessDimensionResponse",
    "DimensionFinding",
    "ErrorCode",
    "ErrorKind",
    "FakeClient",
    "FieldEvaluation",
    "FieldEvaluationResponse",
    "IntakeSnapshot",
    "ModelClient",
    "ModelReply",
    "OpenRouterClient",
    "ProviderError",
    "RunError",
    "ScoreCriterionRequest",
    "ScoreCriterionResponse",
    "ScoreFinding",
    "TokenUsage",
    "Verdict",
    "VerifiedCitation",
    "aclose",
    "assess_dimension",
    "build_snapshot",
    "client_from_env",
    "evaluate_field",
    "is_field_ready",
    "readiness",
    "reset_settings",
    "score_criterion",
    "settings",
    "shared_client",
    "startup",
]
