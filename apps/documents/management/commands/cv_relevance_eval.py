"""Measure the CV relevance question on the owner's labelled set (spec §7.2).

PAID: one Jev call per gold row (about $0.00004 each). record=False -- the
rows are CV lines -- so nothing reaches DecisionRecord. Run files go OUTSIDE
any worktree (CLAUDE.md memory: a removed worktree took a paid run with it).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.test import override_settings

from apps.documents import relevance_eval
from apps.documents.coverage import Item
from apps.funding.models import Program

_GOLD = Path(settings.BASE_DIR) / "docs" / "research" / "cv-relevance-gold.csv"


def _slug(model_id: str) -> str:
    return model_id.replace("/", "_").replace(":", "_")


class Command(BaseCommand):
    help = "Score the CV relevance question against the owner's labels, per language and model."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--gold", default=str(_GOLD))
        parser.add_argument("--out", required=True)
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument(
            "--models",
            default="",
            help=(
                "Comma-separated Jev model IDs to evaluate (e.g. "
                "typesafe/jev-1.13,typesafe/jev-1.14). Defaults to settings.TYPESAFE_MODEL."
            ),
        )

    def handle(self, *args: object, **options: object) -> None:
        out = Path(str(options["out"])).expanduser().resolve()
        repo = Path(settings.BASE_DIR).resolve()
        if out == repo or repo in out.parents:
            raise CommandError("run files live outside the repository, e.g. "
                               "~/agent-workspace/elmify-runs/cv-relevance/<run>")
        rows = relevance_eval.load_gold(Path(str(options["gold"])))
        limit = int(str(options["limit"]))
        if limit:
            rows = rows[:limit]
        raw_models = str(options.get("models") or "").strip()
        models = (
            [m.strip() for m in raw_models.split(",") if m.strip()]
            if raw_models
            else [settings.TYPESAFE_MODEL]
        )
        out.mkdir(parents=True, exist_ok=True)
        sentences_by_programme: dict[object, tuple[str, ...]] = {}
        scores_by_model: dict[str, list[float]] = {}
        for model_id in models:
            scores: list[float] = []
            csv_name = "scores.csv" if len(models) == 1 else f"scores_{_slug(model_id)}.csv"
            with (
                override_settings(TYPESAFE_MODEL=model_id),
                (out / csv_name).open("w", newline="", encoding="utf-8") as handle,
            ):
                writer = csv.writer(handle)
                writer.writerow(["set_id", "language", "owner_label", "answer", "p_unrelated"])
                for row in rows:
                    programme = Program.objects.get(id=row.programme_id)
                    if programme.id not in sentences_by_programme:
                        sentences_by_programme[programme.id] = (
                            relevance_eval.requirement_sentences(programme)
                        )
                    item = Item(row.section, row.section, 0, row.item_text, None)
                    verdict = relevance_eval.ask_item(
                        item, programme=programme, sentences=sentences_by_programme[programme.id]
                    )
                    scores.append(verdict.unrelated)
                    writer.writerow([row.set_id, row.language, row.owner_label, verdict.answer,
                                     f"{verdict.unrelated:.4f}"])
            scores_by_model[model_id] = scores
            result = relevance_eval.report(rows, scores, bar=settings.CV_RELEVANCE_BAR)
            report_name = "report.json" if len(models) == 1 else f"report_{_slug(model_id)}.json"
            (out / report_name).write_text(json.dumps(result, indent=2, default=str))
            for language, line in result.items():
                prefix = f"[{model_id}] " if len(models) > 1 else ""
                self.stdout.write(f"{prefix}{language}: {line}")
        if len(models) > 1:
            comparison = relevance_eval.compare_models(
                rows, scores_by_model, bar=settings.CV_RELEVANCE_BAR
            )
            (out / "comparison.json").write_text(json.dumps(comparison, indent=2, default=str))
