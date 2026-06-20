"""Business logic for the teacher tests & scores endpoints."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.academics.models import Section, StudentEnrollment, TeacherAssignment
from apps.academics.teacher_services import assigned_section
from apps.attendance.models import Attendance, AttendanceStatus
from apps.core.exceptions import Conflict, Forbidden, NotFound, ValidationFailed
from apps.core.helpers import roll_to_int, today_local
from apps.exams.models import (
    MCQOption,
    Question,
    ReportCard,
    Test,
    TestScore,
    TestType,
)

PASS_THRESHOLD_PCT = 35  # <35% is "below pass"

_BANDS = [
    {"label": "Excellent",  "range": "80-100%", "min": 80, "max": 101},
    {"label": "Good",       "range": "60-79%",  "min": 60, "max": 80},
    {"label": "Average",    "range": "35-59%",  "min": 35, "max": 60},
    {"label": "Below Pass", "range": "< 35%",   "min": 0,  "max": 35},
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _derive_status(test: Test, now: datetime) -> str:
    """
    Status derivation for both offline and online tests.

    Offline:
      draft → scheduled → grading → published

    Online:
      draft → scheduled → live → published (closed)
    """
    today = now.date()

    if test.mode == "online":
        if test.published_at is None:
            return "draft"
        if test.available_from and test.available_from > now:
            return "scheduled"
        if test.available_until and test.available_until < now:
            return "published"   # window closed — results available
        return "live"

    # offline
    if test.published_at is not None:
        return "published"
    if test.test_date > today:
        return "scheduled"
    return "grading"


def _question_count(test: Test) -> int:
    return Question.objects.filter(test=test).count()


def _test_to_dict(
    test: Test,
    section_label: str,
    subject_name: str,
    total_students: int,
    now: datetime,
) -> dict:
    status = _derive_status(test, now)
    scores = list(test.scores.all())

    avg_score = None
    submissions = None

    if status == "published" and test.mode == "offline":
        non_absent = [
            s for s in scores
            if not s.is_absent and s.marks_obtained is not None
        ]
        if non_absent and test.max_marks and test.max_marks > 0:
            pcts = [float(s.marks_obtained) / test.max_marks * 100 for s in non_absent]
            avg_score = round(sum(pcts) / len(pcts))
    elif status == "grading":
        entered = [s for s in scores if s.is_absent or s.marks_obtained is not None]
        submissions = len(entered)
    elif test.mode == "online" and status == "live":
        submissions = len(scores)

    return {
        "id": str(test.id),
        "title": test.name,
        "subject": subject_name,
        "class_label": section_label,
        "class_id": str(test.section_id),
        "date": test.test_date.isoformat(),
        "duration_min": test.duration_min,
        "questions": _question_count(test),
        "max_marks": test.max_marks or 0,
        "status": status,
        "mode": test.mode,
        "available_from": test.available_from.isoformat() if test.available_from else None,
        "available_until": test.available_until.isoformat() if test.available_until else None,
        "avg_score": avg_score,
        "submissions": submissions,
        "total_students": total_students,
    }


def _get_assigned_test(teacher: Any, test_id: int, academic_year_id: int | None) -> Test:
    """Fetch test and verify the teacher is assigned to its section (else 404)."""
    test = (
        Test.objects.filter(id=test_id)
        .select_related("section__class_obj", "subject", "school")
        .prefetch_related("scores")
        .first()
    )
    if test is None:
        raise NotFound("Test not found.")
    if not TeacherAssignment.objects.filter(
        teacher=teacher,
        section_id=test.section_id,
        academic_year_id=academic_year_id,
    ).exists():
        raise NotFound("Test not found.")
    return test


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

def list_tests(
    *,
    teacher: Any,
    academic_year_id: int | None,
    status_filter: str | None = None,
) -> list[dict]:
    """All tests for sections the teacher is assigned to this academic year."""
    now = timezone.now()
    section_ids = list(
        TeacherAssignment.objects.filter(
            teacher=teacher, academic_year_id=academic_year_id
        )
        .values_list("section_id", flat=True)
        .distinct()
    )
    tests = (
        Test.objects.filter(section_id__in=section_ids)
        .select_related("section__class_obj", "subject")
        .prefetch_related("scores")
        .order_by("-test_date", "-id")
    )

    result = []
    for test in tests:
        section = test.section
        section_label = f"{section.class_obj.name} — {section.name}"
        total = StudentEnrollment.objects.filter(
            section=section, status="active"
        ).count()
        row = _test_to_dict(test, section_label, test.subject.name, total, now)
        if status_filter and row["status"] != status_filter:
            continue
        result.append(row)
    return result


def get_test(
    *,
    teacher: Any,
    test_id: int,
    academic_year_id: int | None,
) -> dict:
    now = timezone.now()
    test = _get_assigned_test(teacher, test_id, academic_year_id)
    section = test.section
    section_label = f"{section.class_obj.name} — {section.name}"
    total = StudentEnrollment.objects.filter(
        section=section, status="active"
    ).count()
    return _test_to_dict(test, section_label, test.subject.name, total, now)


def delete_test(*, teacher: Any, test_id: int) -> dict:
    """Delete a test the teacher owns, cascading questions, scores and
    submissions. Everything is deletable except a published test (its results
    are out). 404 unknown, 403 another teacher's, 409 published."""
    test = Test.objects.filter(id=test_id).select_related("section").first()
    if test is None:
        raise NotFound("Test not found.")
    if test.created_by_id != teacher.id:
        raise Forbidden("You can't delete another teacher's test.")
    if _derive_status(test, timezone.now()) == "published":
        raise Conflict("A published test can't be deleted.")
    # FKs from Question/TestScore/TestSubmission cascade, so no orphans remain.
    test.delete()
    return {"message": "Test deleted"}


def create_test(
    *,
    teacher: Any,
    academic_year_id: int | None,
    section_id: int,
    name: str,
    test_type: str,
    test_date: date,
    max_marks: int | None = None,
    mode: str = "offline",
    available_from: datetime | None = None,
    available_until: datetime | None = None,
    duration_min: int = 0,
) -> dict:
    section = assigned_section(
        teacher=teacher, section_id=section_id, academic_year_id=academic_year_id
    )
    assignment = (
        TeacherAssignment.objects.filter(
            teacher=teacher, section=section, academic_year_id=academic_year_id
        )
        .select_related("subject")
        .first()
    )
    if assignment is None:
        raise NotFound("No subject assignment found for this section.")

    if mode == "offline" and max_marks is None:
        raise ValidationFailed("max_marks is required for offline tests.")
    if mode == "online":
        if available_from is None or available_until is None:
            raise ValidationFailed(
                "available_from and available_until are required for online tests."
            )
        if available_until <= available_from:
            raise ValidationFailed("available_until must be after available_from.")

    test_type_val = test_type if test_type in TestType.values else TestType.OTHER
    test = Test.objects.create(
        school=section.school,
        section=section,
        subject=assignment.subject,
        name=name,
        test_type=test_type_val,
        mode=mode,
        test_date=test_date,
        max_marks=max_marks,
        available_from=available_from,
        available_until=available_until,
        duration_min=duration_min,
        created_by=teacher,
    )
    now = timezone.now()
    section_label = f"{section.class_obj.name} — {section.name}"
    total = StudentEnrollment.objects.filter(
        section=section, status="active"
    ).count()
    return _test_to_dict(test, section_label, assignment.subject.name, total, now)


# ---------------------------------------------------------------------------
# Question builder (online tests)
# ---------------------------------------------------------------------------

def get_questions(
    *,
    teacher: Any,
    test_id: int,
    academic_year_id: int | None,
) -> list[dict]:
    test = _get_assigned_test(teacher, test_id, academic_year_id)
    if test.mode != "online":
        raise ValidationFailed("Questions are only available for online tests.")

    qs = (
        Question.objects.filter(test=test)
        .prefetch_related("options")
        .order_by("display_order", "id")
    )
    result = []
    for q in qs:
        options = [
            {
                "id": str(opt.id),
                "text": opt.text,
                "is_correct": opt.is_correct,
                "display_order": opt.display_order,
            }
            for opt in q.options.all()
        ]
        result.append({
            "id": str(q.id),
            "question_type": q.question_type,
            "text": q.text,
            "marks": q.marks,
            "display_order": q.display_order,
            "difficulty": q.difficulty,
            "topic": q.topic,
            "options": options,
            "correct_answer": q.correct_answer,
            "explanation": q.explanation,
        })
    return result


def save_questions(
    *,
    teacher: Any,
    test_id: int,
    academic_year_id: int | None,
    questions: list[dict],
    publish: bool,
) -> dict:
    test = _get_assigned_test(teacher, test_id, academic_year_id)
    if test.mode != "online":
        raise ValidationFailed("Questions can only be saved for online tests.")
    if test.published_at is not None:
        raise ValidationFailed("Cannot edit questions on a published test.")

    # Validate questions
    for i, q in enumerate(questions):
        q_type = q.get("question_type")
        if q_type not in ("mcq", "short_answer"):
            raise ValidationFailed(f"Question {i + 1}: invalid question_type '{q_type}'.")
        if not q.get("text", "").strip():
            raise ValidationFailed(f"Question {i + 1}: text is required.")
        if q_type == "mcq":
            options = q.get("options") or []
            if len(options) != 4:
                raise ValidationFailed(f"Question {i + 1}: MCQ requires exactly 4 options.")
            correct = [o for o in options if o.get("is_correct")]
            if len(correct) != 1:
                raise ValidationFailed(
                    f"Question {i + 1}: exactly one option must be marked correct."
                )
        if q_type == "short_answer" and not q.get("correct_answer", "").strip():
            raise ValidationFailed(f"Question {i + 1}: correct_answer is required.")

    with transaction.atomic():
        # Bulk-replace: delete existing, recreate
        Question.objects.filter(test=test).delete()

        total_marks = 0
        for i, q in enumerate(questions):
            question = Question.objects.create(
                school=test.school,
                test=test,
                question_type=q["question_type"],
                text=q["text"].strip(),
                marks=int(q.get("marks", 1)),
                display_order=i,
                difficulty=q.get("difficulty") or "",
                topic=q.get("topic", "").strip(),
                correct_answer=q.get("correct_answer", "").strip(),
                explanation=q.get("explanation", "").strip(),
            )
            total_marks += question.marks

            if q["question_type"] == "mcq":
                for opt in (q.get("options") or []):
                    MCQOption.objects.create(
                        question=question,
                        text=opt["text"].strip(),
                        is_correct=bool(opt.get("is_correct", False)),
                        display_order=int(opt["display_order"]),
                    )

        # Auto-calculate max_marks from question marks sum
        test.max_marks = total_marks
        if publish:
            test.published_at = timezone.now()
            test.save(update_fields=["max_marks", "published_at", "updated_at"])
        else:
            test.save(update_fields=["max_marks", "updated_at"])

    return {"saved": len(questions), "total_marks": total_marks, "published": publish}


# ---------------------------------------------------------------------------
# Marks roster / save marks (offline tests)
# ---------------------------------------------------------------------------

def get_marks_roster(
    *,
    teacher: Any,
    test_id: int,
    academic_year_id: int | None,
) -> list[dict]:
    test = _get_assigned_test(teacher, test_id, academic_year_id)
    enrollments = (
        StudentEnrollment.objects.filter(section=test.section, status="active")
        .select_related("student")
    )
    existing = {
        str(s.student_id): s for s in TestScore.objects.filter(test=test)
    }
    rows = []
    for e in enrollments:
        sid = str(e.student.id)
        score = existing.get(sid)
        rows.append({
            "student_id": sid,
            "roll_no": roll_to_int(e.roll_number),
            "name": e.student.full_name,
            "marks_obtained": score.marks_obtained if score else None,
            "is_absent": score.is_absent if score else False,
        })
    rows.sort(key=lambda r: (r["roll_no"] is None, r["roll_no"] or 0, r["name"]))
    return rows


def save_marks(
    *,
    teacher: Any,
    test_id: int,
    academic_year_id: int | None,
    records: list[dict],
    publish: bool,
) -> dict:
    test = _get_assigned_test(teacher, test_id, academic_year_id)
    if test.published_at is not None:
        raise ValidationFailed("Cannot edit marks on a published test.")

    saved = 0
    with transaction.atomic():
        for rec in records:
            student_id = int(rec["student_id"])
            is_absent = bool(rec.get("is_absent", False))
            marks_obtained = rec.get("marks_obtained")
            if is_absent:
                marks_obtained = None
            TestScore.objects.update_or_create(
                school=test.school,
                test=test,
                student_id=student_id,
                defaults={
                    "marks_obtained": marks_obtained,
                    "is_absent": is_absent,
                    "entered_by": teacher,
                },
            )
            saved += 1
        if publish:
            test.published_at = timezone.now()
            test.save(update_fields=["published_at", "updated_at"])

    return {"saved": saved, "published": publish}


# ---------------------------------------------------------------------------
# Report (offline tests)
# ---------------------------------------------------------------------------

def get_report(
    *,
    teacher: Any,
    test_id: int,
    academic_year_id: int | None,
) -> dict:
    now = timezone.now()
    test = _get_assigned_test(teacher, test_id, academic_year_id)
    section = test.section
    section_label = f"{section.class_obj.name} — {section.name}"
    total_students = StudentEnrollment.objects.filter(
        section=section, status="active"
    ).count()
    test_out = _test_to_dict(
        test, section_label, test.subject.name, total_students, now
    )

    enrollments = (
        StudentEnrollment.objects.filter(section=section, status="active")
        .select_related("student")
    )
    scores_map = {
        str(s.student_id): s for s in TestScore.objects.filter(test=test)
    }

    students = []
    for e in enrollments:
        sid = str(e.student.id)
        score = scores_map.get(sid)
        is_absent = score.is_absent if score else False
        marks = score.marks_obtained if score and not is_absent else None
        pct = (
            round(float(marks) / test.max_marks * 100)
            if marks is not None and test.max_marks and test.max_marks > 0
            else None
        )
        students.append(
            {
                "student_id": sid,
                "roll_no": roll_to_int(e.roll_number),
                "name": e.student.full_name,
                "marks": marks,
                "pct": pct,
                "is_absent": is_absent,
            }
        )
    students.sort(key=lambda r: (r["pct"] is None, -(r["pct"] or 0)))

    scored = [s for s in students if s["pct"] is not None]
    avg = round(sum(s["pct"] for s in scored) / len(scored)) if scored else 0  # type: ignore[arg-type]
    top = scored[0] if scored else None
    passed = sum(1 for s in scored if (s["pct"] or 0) >= PASS_THRESHOLD_PCT)
    pass_rate = round(passed / len(scored) * 100) if scored else 0

    bands = []
    for band in _BANDS:
        count = sum(
            1 for s in scored if band["min"] <= (s["pct"] or 0) < band["max"]
        )
        bands.append({"label": band["label"], "range": band["range"], "count": count})

    return {
        "test": test_out,
        "students": students,
        "avg": avg,
        "top_score": top["marks"] if top else None,
        "top_student": top["name"] if top else None,
        "passed": passed,
        "pass_rate": pass_rate,
        "total": len(students),
        "bands": bands,
    }


# ---------------------------------------------------------------------------
# Report cards — class-teacher generate + publish
# ---------------------------------------------------------------------------


def _grade(pct: float) -> str:
    """AP State Board grade bands."""
    if pct >= 91:
        return "A1"
    if pct >= 81:
        return "A2"
    if pct >= 71:
        return "B1"
    if pct >= 61:
        return "B2"
    if pct >= 51:
        return "C1"
    if pct >= 41:
        return "C2"
    if pct >= 33:
        return "D"
    return "E"


def _class_teacher_section(*, teacher: Any, section_id: int, academic_year_id: int | None) -> Section:
    """Return the section only if this teacher is its class teacher, else 404.
    Report cards span all subjects, so only the class teacher owns them."""
    section = Section.objects.filter(id=section_id).select_related("class_obj__academic_year").first()
    if section is None or section.class_teacher_id != teacher.id:
        raise NotFound("Class not found.")
    return section


def _attendance_pct(student_id: int) -> int:
    """Present / total over the student's recorded attendance (year to date)."""
    qs = Attendance.objects.filter(student_id=student_id)
    total = qs.count()
    if not total:
        return 0
    absent = qs.filter(status=AttendanceStatus.ABSENT).count()
    return round((total - absent) / total * 100)


def _section_student_ids(section: Section) -> list[int]:
    return list(
        StudentEnrollment.objects.filter(section=section, status="active").values_list(
            "student_id", flat=True
        )
    )


def section_report_summary(section: Section, academic_year_id: int | None) -> dict:
    """Report-card status for one section: roll size + how many distinct
    reports (terms) exist this year. Shared by the teacher and admin APIs."""
    student_ids = _section_student_ids(section)
    report_count = (
        ReportCard.objects.filter(
            student_id__in=student_ids, academic_year_id=academic_year_id
        )
        .values("term")
        .distinct()
        .count()
    )
    return {
        "section_id": str(section.id),
        "class_name": section.class_obj.name,
        "section": section.name,
        "student_count": len(student_ids),
        "report_count": report_count,
    }


def list_report_card_sections(*, teacher: Any, academic_year_id: int | None) -> list[dict]:
    sections = (
        Section.objects.filter(
            class_teacher=teacher, class_obj__academic_year_id=academic_year_id
        )
        .select_related("class_obj")
        .order_by("class_obj__display_order", "name")
    )
    return [section_report_summary(s, academic_year_id) for s in sections]


def list_report_card_reports(
    *, teacher: Any, section_id: int, academic_year_id: int | None
) -> list[dict]:
    """History: the section's report cards grouped by name (term)."""
    section = _class_teacher_section(
        teacher=teacher, section_id=section_id, academic_year_id=academic_year_id
    )
    student_ids = _section_student_ids(section)
    cards = ReportCard.objects.filter(
        student_id__in=student_ids, academic_year_id=academic_year_id
    )
    by_name: dict[str, dict] = {}
    for c in cards:
        b = by_name.setdefault(
            c.term,
            {
                "name": c.term,
                "total_students": 0,
                "published_count": 0,
                "draft_count": 0,
                "updated_at": None,
            },
        )
        b["total_students"] += 1
        if c.published_at is not None:
            b["published_count"] += 1
        else:
            b["draft_count"] += 1
        iso = c.updated_at.isoformat() if c.updated_at else None
        if iso and (b["updated_at"] is None or iso > b["updated_at"]):
            b["updated_at"] = iso
    return sorted(by_name.values(), key=lambda r: r["updated_at"] or "", reverse=True)


def _subjects_from_snapshot(card: ReportCard) -> list[dict]:
    snap = card.data_snapshot or {}
    return [
        {"name": s["name"], "max_marks": s.get("maxMarks", 100)}
        for s in snap.get("subjects", [])
    ]


def report_card_roster(
    *, teacher: Any, section_id: int, academic_year_id: int | None, name: str | None
) -> dict:
    section = _class_teacher_section(
        teacher=teacher, section_id=section_id, academic_year_id=academic_year_id
    )
    return roster_for_section(section=section, academic_year_id=academic_year_id, name=name)


def roster_for_section(
    *, section: Section, academic_year_id: int | None, name: str | None
) -> dict:
    """Roster for an existing named report, or a blank roster seeded with the
    section's most recent report's subjects (template) when creating a new one.
    Shared by the teacher and admin APIs."""
    enrollments = list(
        StudentEnrollment.objects.filter(section=section, status="active").select_related("student")
    )
    student_ids = [e.student_id for e in enrollments]

    name = (name or "").strip()
    existing: dict[int, ReportCard] = {}
    if name:
        existing = {
            c.student_id: c
            for c in ReportCard.objects.filter(
                student_id__in=student_ids, academic_year_id=academic_year_id, term=name
            )
        }

    if existing:
        subjects = _subjects_from_snapshot(next(iter(existing.values())))
    else:
        # Template: subjects from the section's most recent report (if any).
        latest = (
            ReportCard.objects.filter(
                student_id__in=student_ids, academic_year_id=academic_year_id
            )
            .order_by("-generated_at", "-id")
            .first()
        )
        subjects = _subjects_from_snapshot(latest) if latest else []

    subject_names = [s["name"] for s in subjects]
    students = []
    for e in enrollments:
        card = existing.get(e.student_id)
        if card:
            snap = card.data_snapshot or {}
            saved = {s["name"]: s.get("marks") for s in snap.get("subjects", [])}
            marks = {n: saved.get(n) for n in subject_names}
            remark = snap.get("teacherRemark", "")
            published = card.published_at is not None
        else:
            marks = dict.fromkeys(subject_names)
            remark = ""
            published = False
        students.append(
            {
                "student_id": str(e.student_id),
                "roll_no": roll_to_int(e.roll_number),
                "name": e.student.full_name,
                "attendance_pct": _attendance_pct(e.student_id),
                "remark": remark,
                "marks": marks,
                "already_published": published,
            }
        )
    students.sort(key=lambda r: (r["roll_no"] is None, r["roll_no"] or 0, r["name"]))
    return {
        "section_id": str(section.id),
        "class_name": section.class_obj.name,
        "section": section.name,
        "name": name,
        "subjects": subjects,
        "students": students,
    }


def save_report_cards(
    *,
    teacher: Any,
    section_id: int,
    academic_year_id: int | None,
    name: str,
    subjects: list[dict],
    publish: bool,
    records: list[dict],
) -> dict:
    section = _class_teacher_section(
        teacher=teacher, section_id=section_id, academic_year_id=academic_year_id
    )
    return save_report_cards_for_section(
        section=section,
        name=name,
        subjects=subjects,
        publish=publish,
        records=records,
        generated_by=teacher,
    )


def save_report_cards_for_section(
    *,
    section: Section,
    name: str,
    subjects: list[dict],
    publish: bool,
    records: list[dict],
    generated_by: Any = None,
) -> dict:
    """Persist/publish a section's report cards. Shared by the teacher and admin
    APIs; ``generated_by`` is the Teacher when a teacher saves, else None."""
    name = (name or "").strip()
    if not name:
        raise ValidationFailed("Report name is required.")
    if len(name) > 60:
        raise ValidationFailed("Report name is too long (max 60 characters).")

    # Normalize the subjects: drop blanks / non-positive max.
    norm_subjects: list[dict] = []
    for s in subjects:
        sname = (s.get("name") or "").strip()
        try:
            smax = int(s.get("max_marks") or 0)
        except (TypeError, ValueError):
            smax = 0
        if sname and smax > 0:
            norm_subjects.append({"name": sname, "max_marks": smax})
    if not norm_subjects:
        raise ValidationFailed("Add at least one subject with a max score.")

    year = section.class_obj.academic_year
    issue_date = today_local().isoformat()
    valid_ids = set(_section_student_ids(section))

    # First pass: build each student's subject grid + overall (for ranking).
    computed = []
    for rec in records:
        sid = int(rec["student_id"])
        if sid not in valid_ids:
            continue
        marks_in = rec.get("marks") or {}
        subj_payload = []
        total_marks = 0
        total_max = 0
        for sub in norm_subjects:
            sname, smax = sub["name"], sub["max_marks"]
            raw = marks_in.get(sname)
            mark = max(0, min(smax, int(raw))) if raw is not None else None
            sub_pct = (mark / smax * 100) if mark is not None else None
            subj_payload.append(
                {
                    "name": sname,
                    "maxMarks": smax,
                    "marks": mark,
                    "grade": _grade(sub_pct) if sub_pct is not None else "-",
                }
            )
            if mark is not None:
                total_marks += mark
                total_max += smax
        overall = round(total_marks / total_max * 100) if total_max else 0
        computed.append(
            {
                "sid": sid,
                "subjects": subj_payload,
                "overall": overall,
                "remark": rec.get("remark", ""),
                # Per-student publish override (True/False/None). True is an
                # explicit "(re)publish this student".
                "explicit_publish": rec.get("publish"),
            }
        )

    existing = {
        c.student_id: c
        for c in ReportCard.objects.filter(
            student_id__in=[c["sid"] for c in computed], academic_year=year, term=name
        )
    }

    total_students = len(computed)
    now = timezone.now()
    saved = 0
    published_count = 0
    with transaction.atomic():
        for c in computed:
            rank = sum(1 for o in computed if o["overall"] > c["overall"]) + 1
            prior = existing.get(c["sid"])
            prior_published = prior is not None and prior.published_at is not None
            explicit = c["explicit_publish"] is True
            # An already-published report is immutable except via an explicit
            # per-student re-publish — so "Publish all" / "Save draft" leave it
            # untouched (no re-stamp, no snapshot overwrite).
            if prior_published and not explicit:
                if prior.published_at is not None:
                    published_count += 1
                continue
            published_at = now if (explicit or publish) else None
            snapshot = {
                "term": name,
                "academicYear": year.label,
                "issueDate": issue_date,
                "subjects": c["subjects"],
                "attendancePct": _attendance_pct(c["sid"]),
                "teacherRemark": c["remark"],
                "principalRemark": None,
                "overallGrade": _grade(c["overall"]),
                "overallPct": c["overall"],
                "rank": rank,
                "totalStudents": total_students,
            }
            ReportCard.objects.update_or_create(
                student_id=c["sid"],
                academic_year=year,
                term=name,
                defaults={
                    "school": section.school,
                    "generated_by": generated_by,
                    "data_snapshot": snapshot,
                    "published_at": published_at,
                },
            )
            saved += 1
            if published_at is not None:
                published_count += 1
    return {"saved": saved, "published": published_count}
