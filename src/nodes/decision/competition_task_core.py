"""ROS-independent competition task selection helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence, Tuple


ZONE_LETTERS: Tuple[str, ...] = tuple("ABCD")


@dataclass(frozen=True)
class ZoneAssessment:
    letter: str
    abnormal: bool
    confidence: float = 0.0


def normalize_zone_order(values: Sequence[str]) -> Tuple[str, ...]:
    order = tuple(str(value).strip().upper() for value in values)
    if len(order) != len(ZONE_LETTERS) or set(order) != set(ZONE_LETTERS):
        raise ValueError("abnormal_zone_fallback_order must be a permutation of A/B/C/D")
    return order


def freeze_two_zone_tasks(
    assessments: Iterable[ZoneAssessment],
    fallback_order: Sequence[str] = ZONE_LETTERS,
) -> Tuple[str, str]:
    """Return exactly two distinct frozen placement targets.

    Two detections are used directly. Three or four are ranked by abnormal
    confidence. Zero or one detection is completed from the configured order.
    """

    order = normalize_zone_order(fallback_order)
    rank = {letter: index for index, letter in enumerate(order)}
    normalized = []
    seen = set()
    for assessment in assessments:
        letter = str(assessment.letter).strip().upper()
        confidence = float(assessment.confidence)
        if letter not in rank:
            raise ValueError("zone assessment letter must be A/B/C/D")
        if letter in seen:
            raise ValueError("zone assessments must not contain duplicates")
        if not math.isfinite(confidence) or confidence < 0.0:
            raise ValueError("zone assessment confidence must be finite and non-negative")
        seen.add(letter)
        normalized.append(ZoneAssessment(letter, bool(assessment.abnormal), confidence))

    abnormal = [assessment for assessment in normalized if assessment.abnormal]
    if len(abnormal) == 2:
        selected = [assessment.letter for assessment in abnormal]
    elif len(abnormal) >= 3:
        selected = [
            assessment.letter
            for assessment in sorted(
                abnormal,
                key=lambda item: (-item.confidence, rank[item.letter]),
            )[:2]
        ]
    else:
        selected = [assessment.letter for assessment in abnormal]
        selected.extend(
            letter for letter in order
            if letter not in selected
        )
        selected = selected[:2]

    if len(selected) != 2 or selected[0] == selected[1]:
        raise RuntimeError("competition task selection did not produce two distinct zones")
    return selected[0], selected[1]
