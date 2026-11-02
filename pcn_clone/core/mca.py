"""The MCA calculator: weighted points, percent of maximum and priority band.

The summary is computed over a complete score map only: a missing
criterion, an unknown criterion or an off-scale value raises rather than
producing partial arithmetic. ``percent_of_maximum`` is weighted points as a
share of the maximum attainable (max scale value × total weight), kept at
full precision; rounding is a display concern. The band is the first band
(thresholds descend) whose inclusive lower bound the percentage meets.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pcn_clone.content.models import McaBand, McaMatrix
from pcn_clone.core.jsstr import js_object_keys, js_to_string, number_to_string


class McaScoreError(ValueError):
    """A score map is incomplete, names an unknown criterion, or is off-scale."""


@dataclass(frozen=True, slots=True)
class McaSummaryRow:
    """One criterion's contribution."""

    criterion_id: str
    label: str
    weight: int
    score: float
    weighted_points: float


@dataclass(frozen=True, slots=True)
class McaSummary:
    """The derived summary over one complete score map."""

    rows: list[McaSummaryRow]
    total_weighted_points: float
    max_weighted_points: int
    percent_of_maximum: float
    band: McaBand


def _score_text(score: Any) -> str:
    return "null" if score is None else js_to_string(score)


def _scale_score(score: Any, scale_values: set[int]) -> float | None:
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    return score if score in scale_values else None


def compute_mca_summary(matrix: McaMatrix, scores: Mapping[str, Any]) -> McaSummary:
    """Summarise one complete score map against the matrix.

    Raises ``McaScoreError`` for an unknown criterion, a missing criterion or
    a score that is not a value on the matrix's scale.
    """
    criterion_ids = [criterion.id for criterion in matrix.criteria]
    for key in js_object_keys(scores):
        if key not in criterion_ids:
            raise McaScoreError(
                f'Score map names unknown criterion "{key}" — the matrix defines '
                f"[{', '.join(dict.fromkeys(criterion_ids))}]."
            )

    scale_values = {entry.value for entry in matrix.scale}
    rows: list[McaSummaryRow] = []
    for criterion in matrix.criteria:
        if criterion.id not in scores:
            raise McaScoreError(
                f'Score map is missing criterion "{criterion.id}" — the summary '
                "is computed over a complete map only, never partially."
            )
        score = _scale_score(scores[criterion.id], scale_values)
        if score is None:
            raise McaScoreError(
                f"Score {_score_text(scores[criterion.id])} for criterion "
                f'"{criterion.id}" is not a value on the matrix\'s scale.'
            )
        rows.append(
            McaSummaryRow(
                criterion_id=criterion.id,
                label=criterion.label,
                weight=criterion.weight,
                score=score,
                weighted_points=score * criterion.weight,
            )
        )

    total_weighted_points: float = 0
    total_weight = 0
    for row in rows:
        total_weighted_points += row.weighted_points
        total_weight += row.weight
    max_weighted_points = matrix.scale_maximum * total_weight
    percent_of_maximum = (total_weighted_points / max_weighted_points) * 100

    band = next(
        (b for b in matrix.bands if percent_of_maximum >= b.min_percent_of_maximum),
        None,
    )
    if band is None:
        raise McaScoreError(
            "No band matched percent-of-maximum "
            f"{number_to_string(percent_of_maximum)} — the matrix bands do not "
            "cover 0."
        )

    return McaSummary(
        rows=rows,
        total_weighted_points=total_weighted_points,
        max_weighted_points=max_weighted_points,
        percent_of_maximum=percent_of_maximum,
        band=band,
    )
