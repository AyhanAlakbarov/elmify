"""Scoring the relevance question against the owner's labels (spec §7.2).

Pass mark: of the items Jev would leave out, at least 98% are ones the owner
also left out. Scored per language; a language below the mark stays off
(settings.CV_RELEVANCE_LANGUAGES). The bar itself is the Learn-then-Test bar
the funding readers use (engine_eval.score.ltt_bar), so the owner gets a
bar with a guarantee rather than a guessed 0.9.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from apps.research.engine_eval.score import ltt_bar

from .relevance import (
    REACH,
    ask_item,
    requirement_sentences,
)

__all__ = [
    "LABELS",
    "LANGUAGES",
    "PASS_MARK",
    "REACH",
    "GoldRow",
    "ask_item",
    "compare_models",
    "compare_skills",
    "load_gold",
    "report",
    "report_by_section",
    "requirement_sentences",
]

PASS_MARK = 0.98
LANGUAGES = ("en", "tr", "ru", "az")
LABELS = ("keep", "leave_out")


@dataclass(frozen=True)
class GoldRow:
    set_id: str
    programme_id: UUID
    section: str
    item_text: str
    language: str
    owner_label: str


def load_gold(path: Path) -> list[GoldRow]:
    rows: list[GoldRow] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for number, raw in enumerate(csv.DictReader(handle), start=2):
            try:
                row = GoldRow(raw["set_id"], UUID(raw["programme_id"]), raw["section"],
                              raw["item_text"].strip(), raw["language"], raw["owner_label"])
            except (KeyError, ValueError) as error:
                raise ValueError(f"line {number}: {error}") from None
            if (
                row.section not in REACH or row.language not in LANGUAGES
                or row.owner_label not in LABELS or not row.item_text
            ):
                raise ValueError(f"line {number}: outside the closed lists")
            rows.append(row)
    return rows


def report(
    rows: Sequence[GoldRow], scores: Sequence[float], *, bar: float = 0.9
) -> dict[str, dict[str, object]]:
    """Per language: how many items P(unrelated) >= bar would leave out, how
    many of those the owner also left out, and the Learn-then-Test bar."""
    by_language: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for row, score in zip(rows, scores, strict=True):
        by_language[row.language].append((score, row.owner_label == "leave_out"))
    result: dict[str, dict[str, object]] = {}
    for language, pairs in sorted(by_language.items()):
        dropped = [truth for score, truth in pairs if score >= bar]
        precision = sum(dropped) / len(dropped) if dropped else 0.0
        result[language] = {
            "items": len(pairs),
            "left_out_at_bar": len(dropped),
            "precision_at_bar": precision,
            "passes": bool(dropped) and precision >= PASS_MARK,
            "ltt_bar": ltt_bar(pairs, 1 - PASS_MARK),
        }
    return result


def report_by_section(
    rows: Sequence[GoldRow], scores: Sequence[float], *, bar: float = 0.9
) -> dict[str, dict[str, object]]:
    """Per section (including `skills`): precision and Learn-then-Test bar."""
    by_section: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for row, score in zip(rows, scores, strict=True):
        by_section[row.section].append((score, row.owner_label == "leave_out"))
    result: dict[str, dict[str, object]] = {}
    for section, pairs in sorted(by_section.items()):
        dropped = [truth for score, truth in pairs if score >= bar]
        precision = sum(dropped) / len(dropped) if dropped else 0.0
        result[section] = {
            "items": len(pairs),
            "left_out_at_bar": len(dropped),
            "precision_at_bar": precision,
            "passes": bool(dropped) and precision >= PASS_MARK,
            "ltt_bar": ltt_bar(pairs, 1 - PASS_MARK),
        }
    return result


def compare_models(
    rows: Sequence[GoldRow],
    scores_by_model: Mapping[str, Sequence[float]],
    *,
    bar: float = 0.9,
) -> dict[str, object]:
    """Compare two or more Jev model versions (e.g. `typesafe/jev-1.13` vs
    `typesafe/jev-1.14`) on the same labelled rows."""
    models = list(scores_by_model)
    per_model: dict[str, object] = {}
    for model, scores in scores_by_model.items():
        per_model[model] = {
            "by_language": report(rows, scores, bar=bar),
            "by_section": report_by_section(rows, scores, bar=bar),
        }
    disagreements: list[dict[str, object]] = []
    if len(models) >= 2:
        first, second = models[0], models[1]
        for row, s1, s2 in zip(
            rows, scores_by_model[first], scores_by_model[second], strict=True
        ):
            d1, d2 = s1 >= bar, s2 >= bar
            if d1 != d2:
                disagreements.append(
                    {
                        "set_id": row.set_id,
                        "section": row.section,
                        "language": row.language,
                        "owner_label": row.owner_label,
                        first: round(s1, 4),
                        second: round(s2, 4),
                    }
                )
    return {
        "models": per_model,
        "disagreement_count": len(disagreements),
        "agreement_rate": (
            (len(rows) - len(disagreements)) / len(rows) if rows else 1.0
        ),
        "disagreements": disagreements,
    }


def compare_skills(
    skill_verdicts: Mapping[str, tuple[str, float]],
    tailored_matched: Sequence[str],
    *,
    bar: float = 0.9,
) -> dict[str, object]:
    """Head-to-head comparison between Jev's `CVRelevanceSkill` verdicts
    (`skill_name -> (answer, chance)`) and `tailor_skills`'s matched skills.

    Measures whether Jev's relevant (`asked_for` / `same_field`) and drop
    (`unrelated` at `chance >= bar`) verdicts agree with `tailor_skills`.
    """
    tailored_set = {name.strip().casefold() for name in tailored_matched}
    jev_relevant: set[str] = set()
    jev_unrelated: set[str] = set()
    all_skills: set[str] = set()
    for name, (answer, chance) in skill_verdicts.items():
        folded = name.strip().casefold()
        all_skills.add(folded)
        if answer in ("asked_for", "same_field"):
            jev_relevant.add(folded)
        elif answer == "unrelated" and chance >= bar:
            jev_unrelated.add(folded)
    both_relevant = sorted(jev_relevant & tailored_set)
    jev_only = sorted(jev_relevant - tailored_set)
    tailor_only = sorted((tailored_set & all_skills) - jev_relevant)
    contradicted = sorted(jev_unrelated & tailored_set)
    agreement = (
        sum(
            (s in jev_relevant) == (s in tailored_set)
            for s in all_skills
        )
        / len(all_skills)
        if all_skills
        else 1.0
    )
    return {
        "skills_total": len(all_skills),
        "agreement_rate": agreement,
        "both_relevant": both_relevant,
        "jev_only_relevant": jev_only,
        "tailor_only_relevant": tailor_only,
        "jev_unrelated_but_tailor_matched": contradicted,
    }
