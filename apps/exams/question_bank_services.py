"""Question bank: search the global catalog + a teacher's private questions,
and CRUD for a teacher's own questions.

Visibility for a teacher = ``enabled`` AND (global catalog OR authored by them):

    enabled=True AND (created_by IS NULL  OR  created_by=<teacher>)

BankQuestion is a plain model (not tenant-scoped), so every query here is an
explicit, fail-safe filter rather than relying on the TenantManager.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q, QuerySet

from apps.core.exceptions import NotFound, ValidationFailed
from apps.exams.models import BankQuestion

# A single page is capped so an unbounded catalog can't be dumped at once.
MAX_LIMIT = 100

# Difficulty is a fixed scale — present it in pedagogical order, not alphabetical.
_DIFFICULTY_ORDER = ["easy", "medium", "hard"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _visible(teacher: Any) -> QuerySet[BankQuestion]:
    """Questions this teacher may see: enabled global catalog OR own private."""
    return BankQuestion.objects.filter(enabled=True).filter(
        Q(created_by__isnull=True) | Q(created_by_id=teacher.id)
    )


def _to_dict(q: BankQuestion) -> dict:
    return {
        "id": str(q.id),
        "source_id": q.source_id,
        "scope": "catalog" if q.created_by_id is None else "mine",
        "subject": q.subject,
        "grade": q.grade,
        "board": q.board,
        "chapter_number": q.chapter_number,
        "chapter_name": q.chapter_name,
        "topic": q.topic,
        "question_type": q.question_type,
        "difficulty": q.difficulty,
        "text": q.text,
        "options": q.options or [],
        "correct_answer": q.correct_answer,
        "explanation": q.explanation,
        "tags": q.tags or [],
    }


def _validate_content(
    *,
    question_type: str,
    text: str,
    options: list[dict] | None,
    correct_answer: str,
) -> None:
    """Same content rules the test question builder enforces (save_questions)."""
    if question_type not in ("mcq", "short_answer"):
        raise ValidationFailed(f"Invalid question_type '{question_type}'.")
    if not (text or "").strip():
        raise ValidationFailed("Question text is required.")
    if question_type == "mcq":
        opts = options or []
        if len(opts) != 4:
            raise ValidationFailed("MCQ requires exactly 4 options.")
        if sum(1 for o in opts if o.get("is_correct")) != 1:
            raise ValidationFailed("Exactly one option must be marked correct.")
        if any(not (o.get("text") or "").strip() for o in opts):
            raise ValidationFailed("Every option needs text.")
    if question_type == "short_answer" and not (correct_answer or "").strip():
        raise ValidationFailed("correct_answer is required for short-answer questions.")


# ---------------------------------------------------------------------------
# Search / list
# ---------------------------------------------------------------------------

def list_questions(
    *,
    teacher: Any,
    subject: str | None = None,
    chapter: str | None = None,
    topic: str | None = None,
    difficulty: str | None = None,
    scope: str = "all",
    limit: int = 30,
    offset: int = 0,
) -> dict:
    """Filtered, paginated view over the teacher's visible questions.

    All filters are exact matches on values the teacher picked from ``facets``
    (no free-text search). ``scope``: ``catalog`` (global only) | ``mine`` (own
    only) | ``all``. Returns ``{"items": [...], "total": int}``.
    """
    qs = _visible(teacher)

    if scope == "catalog":
        qs = qs.filter(created_by__isnull=True)
    elif scope == "mine":
        qs = qs.filter(created_by_id=teacher.id)

    if subject:
        qs = qs.filter(subject__iexact=subject.strip())
    if chapter:
        qs = qs.filter(chapter_name__iexact=chapter.strip())
    if topic:
        qs = qs.filter(topic__iexact=topic.strip())
    if difficulty:
        qs = qs.filter(difficulty=difficulty.strip())

    total = qs.count()
    limit = max(1, min(int(limit), MAX_LIMIT))
    offset = max(0, int(offset))
    items = [_to_dict(bq) for bq in qs[offset : offset + limit]]
    return {"items": items, "total": total}


def facets(
    *, teacher: Any, subject: str | None = None, chapter: str | None = None
) -> dict:
    """Available filter values across the teacher's visible questions, cascading
    with the filters already chosen so every option always has matches:

    * ``subjects``     — always the full set the teacher can see.
    * ``chapters``     — narrowed to ``subject`` when given.
    * ``topics``       — narrowed to ``subject`` (+ ``chapter`` when given).
    * ``difficulties`` — narrowed to the same scope as topics.

    The frontend re-fetches this as filters change so the dropdowns only ever
    offer values that return questions.

    Note: ``.order_by(<field>)`` is reapplied before each ``.distinct()`` —
    otherwise the model's default ordering leaks extra sort columns into the
    SELECT and defeats the DISTINCT.
    """
    base = _visible(teacher)

    # Subjects: the full universe (independent of the current subject pick).
    subjects = sorted(
        s for s in base.order_by("subject").values_list("subject", flat=True).distinct() if s
    )

    scoped = base
    if subject:
        scoped = scoped.filter(subject__iexact=subject.strip())

    chapters: list[dict] = []
    seen: set[str] = set()
    for cn, name in (
        scoped.exclude(chapter_name="")
        .order_by("chapter_number", "chapter_name")
        .values_list("chapter_number", "chapter_name")
        .distinct()
    ):
        if name in seen:
            continue
        seen.add(name)
        chapters.append({"number": cn, "name": name})

    topic_scope = scoped
    if chapter:
        topic_scope = topic_scope.filter(chapter_name__iexact=chapter.strip())

    topics = sorted(
        t
        for t in topic_scope.exclude(topic="")
        .order_by("topic")
        .values_list("topic", flat=True)
        .distinct()
    )

    present = set(
        topic_scope.exclude(difficulty="").values_list("difficulty", flat=True).distinct()
    )
    difficulties = [d for d in _DIFFICULTY_ORDER if d in present]

    return {
        "subjects": subjects,
        "chapters": chapters,
        "topics": topics,
        "difficulties": difficulties,
    }


# ---------------------------------------------------------------------------
# Private CRUD (a teacher's own questions only)
# ---------------------------------------------------------------------------

def _own_question(teacher: Any, question_id: int) -> BankQuestion:
    """Fetch a question the teacher authored, else 404. Global catalog rows are
    never editable through this path (created_by is null)."""
    bq = BankQuestion.objects.filter(id=question_id, created_by_id=teacher.id).first()
    if bq is None:
        raise NotFound("Question not found.")
    return bq


def create_question(
    *,
    teacher: Any,
    subject: str,
    question_type: str,
    text: str,
    options: list[dict] | None = None,
    correct_answer: str = "",
    difficulty: str = "",
    chapter_name: str = "",
    topic: str = "",
    explanation: str = "",
    tags: list[str] | None = None,
) -> dict:
    subject = (subject or "").strip()
    if not subject:
        raise ValidationFailed("Subject is required.")
    _validate_content(
        question_type=question_type,
        text=text,
        options=options,
        correct_answer=correct_answer,
    )
    norm_options = (
        [{"text": o["text"].strip(), "is_correct": bool(o.get("is_correct"))} for o in (options or [])]
        if question_type == "mcq"
        else []
    )
    bq = BankQuestion.objects.create(
        school_id=teacher.school_id,
        created_by=teacher,
        source_id="",
        subject=subject,
        question_type=question_type,
        text=text.strip(),
        options=norm_options,
        correct_answer=(correct_answer or "").strip() if question_type == "short_answer" else "",
        difficulty=(difficulty or "").strip(),
        chapter_name=(chapter_name or "").strip(),
        topic=(topic or "").strip(),
        explanation=(explanation or "").strip(),
        tags=tags or [],
    )
    return _to_dict(bq)


def update_question(
    *,
    teacher: Any,
    question_id: int,
    subject: str,
    question_type: str,
    text: str,
    options: list[dict] | None = None,
    correct_answer: str = "",
    difficulty: str = "",
    chapter_name: str = "",
    topic: str = "",
    explanation: str = "",
    tags: list[str] | None = None,
) -> dict:
    bq = _own_question(teacher, question_id)
    subject = (subject or "").strip()
    if not subject:
        raise ValidationFailed("Subject is required.")
    _validate_content(
        question_type=question_type,
        text=text,
        options=options,
        correct_answer=correct_answer,
    )
    bq.subject = subject
    bq.question_type = question_type
    bq.text = text.strip()
    bq.options = (
        [{"text": o["text"].strip(), "is_correct": bool(o.get("is_correct"))} for o in (options or [])]
        if question_type == "mcq"
        else []
    )
    bq.correct_answer = (correct_answer or "").strip() if question_type == "short_answer" else ""
    bq.difficulty = (difficulty or "").strip()
    bq.chapter_name = (chapter_name or "").strip()
    bq.topic = (topic or "").strip()
    bq.explanation = (explanation or "").strip()
    bq.tags = tags or []
    bq.save()
    return _to_dict(bq)


def delete_question(*, teacher: Any, question_id: int) -> dict:
    bq = _own_question(teacher, question_id)
    bq.delete()
    return {"message": "Question deleted"}
