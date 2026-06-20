"""Import the global (SmartSkool catalog) question bank from JSONL seed files.

Idempotent: each row is keyed by its source ``id`` and upserted, so re-running
after generating new chapters/subjects just adds or refreshes rows. An admin's
manual ``enabled=False`` toggle is preserved across re-imports (the flag is
never part of the update payload).

Usage:
    uv run python manage.py import_question_bank
    uv run python manage.py import_question_bank --path /some/other/dir
    uv run python manage.py import_question_bank --dry-run

Source schema (one JSON object per line)::

    {"id", "subject", "grade", "board", "chapter_number", "chapter_name",
     "topic", "type", "difficulty", "question", "options"{A..D}, "answer",
     "explanation", "tags"[]}

``type`` is ``mcq`` or ``fill_in_the_blank``; the latter maps to the platform's
``short_answer`` type (graded by case-insensitive match on ``answer``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.exams.models import BankQuestion

# seeds dir bundled in the repo: apps/exams/seeds/question_bank/
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "seeds" / "question_bank"

_DIFFICULTIES = {"easy", "medium", "hard"}


def _map_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Translate one source row into BankQuestion field values, or None to skip."""
    src_type = row.get("type")
    if src_type == "mcq":
        question_type = "mcq"
        opts_map = row.get("options") or {}
        answer = (row.get("answer") or "").strip()
        # Order options by their letter key (A, B, C, D, ...).
        options = [
            {"text": str(opts_map[letter]).strip(), "is_correct": letter == answer}
            for letter in sorted(opts_map)
        ]
        correct_answer = ""
        if not options or sum(o["is_correct"] for o in options) != 1:
            return None  # malformed MCQ — skip rather than import a broken question
    elif src_type == "fill_in_the_blank":
        question_type = "short_answer"
        options = []
        correct_answer = (row.get("answer") or "").strip()
        if not correct_answer:
            return None
    else:
        return None  # unknown type

    difficulty = (row.get("difficulty") or "").strip().lower()
    if difficulty not in _DIFFICULTIES:
        difficulty = ""

    return {
        "subject": (row.get("subject") or "").strip(),
        "grade": row.get("grade"),
        "board": (row.get("board") or "").strip(),
        "chapter_number": row.get("chapter_number"),
        "chapter_name": (row.get("chapter_name") or "").strip(),
        "topic": (row.get("topic") or "").strip(),
        "question_type": question_type,
        "difficulty": difficulty,
        "text": (row.get("question") or "").strip(),
        "options": options,
        "correct_answer": correct_answer,
        "explanation": (row.get("explanation") or "").strip(),
        "tags": row.get("tags") or [],
    }


class Command(BaseCommand):
    help = "Import / refresh the global question-bank catalog from JSONL seeds."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--path",
            default=str(DEFAULT_PATH),
            help=f"Directory of *.jsonl seed files (default: {DEFAULT_PATH}).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and report counts without writing to the database.",
        )

    def handle(self, *args: Any, **opts: Any) -> None:
        base = Path(opts["path"])
        if not base.exists():
            raise CommandError(f"Seed path does not exist: {base}")

        files = sorted(base.rglob("*.jsonl"))
        if not files:
            raise CommandError(f"No .jsonl files found under {base}")

        created = updated = skipped = 0
        with transaction.atomic():
            for fpath in files:
                self.stdout.write(f"· {fpath.relative_to(base)}")
                for lineno, line in enumerate(fpath.read_text().splitlines(), start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise CommandError(f"{fpath}:{lineno} invalid JSON: {exc}") from exc

                    source_id = (row.get("id") or "").strip()
                    if not source_id:
                        skipped += 1
                        continue
                    mapped = _map_row(row)
                    if mapped is None or not mapped["subject"] or not mapped["text"]:
                        skipped += 1
                        continue

                    if opts["dry_run"]:
                        created += 1  # counted as "would import"
                        continue

                    # enabled is intentionally NOT in defaults so an admin's
                    # manual disable survives a re-import; new rows use the
                    # model default (True).
                    _, was_created = BankQuestion.objects.update_or_create(
                        source_id=source_id,
                        created_by=None,
                        defaults={"school": None, **mapped},
                    )
                    created += int(was_created)
                    updated += int(not was_created)

            if opts["dry_run"]:
                transaction.set_rollback(True)

        verb = "Would import" if opts["dry_run"] else "Imported"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb}: {created} created, {updated} updated, {skipped} skipped "
                f"from {len(files)} file(s)."
            )
        )
