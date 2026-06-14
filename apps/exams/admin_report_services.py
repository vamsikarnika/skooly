"""Admin report-card services: read teacher-published cards, generate branded
PDFs, and publish those PDFs to parents.

Scores come from the teacher (``ReportCard`` rows with ``published_at`` set —
already visible to parents). The admin layer is additive: render an optional
branded PDF, attach an optional per-student principal remark, and gate parent
PDF visibility behind ``pdf_published_at``.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.academics.models import Section, StudentEnrollment
from apps.exams.models import ReportCard
from apps.exams.report_card_pdf import generate_and_store_report_card


def _published_cards(section: Section, term: str):  # type: ignore[no-untyped-def]
    """Teacher-published cards for this section + term."""
    year = section.class_obj.academic_year
    student_ids = StudentEnrollment.objects.filter(
        section=section, status="active"
    ).values_list("student_id", flat=True)
    return ReportCard.objects.filter(
        student_id__in=list(student_ids),
        academic_year=year,
        term=term,
        published_at__isnull=False,
    )


def list_terms(section: Section) -> list[dict]:
    """Distinct report terms teachers have published for this section, with
    how many cards exist and how many have a published PDF."""
    cards = _published_cards_all_terms(section)
    by_term: dict[str, dict] = {}
    for c in cards:
        b = by_term.setdefault(
            c.term, {"term": c.term, "card_count": 0, "pdf_published_count": 0}
        )
        b["card_count"] += 1
        if c.pdf_published_at is not None:
            b["pdf_published_count"] += 1
    return sorted(by_term.values(), key=lambda r: r["term"])


def _published_cards_all_terms(section: Section):  # type: ignore[no-untyped-def]
    year = section.class_obj.academic_year
    student_ids = StudentEnrollment.objects.filter(
        section=section, status="active"
    ).values_list("student_id", flat=True)
    return ReportCard.objects.filter(
        student_id__in=list(student_ids), academic_year=year, published_at__isnull=False
    )


def cards_for_section(section: Section, term: str) -> list[dict]:
    """Per-student report cards (scores from the snapshot) for the grid."""
    enrollments = {
        e.student_id: e
        for e in StudentEnrollment.objects.filter(
            section=section, status="active"
        ).select_related("student")
    }
    rows = []
    for c in _published_cards(section, term).select_related("student"):
        snap = c.data_snapshot or {}
        e = enrollments.get(c.student_id)
        roll = _roll(e.roll_number) if e else None
        rows.append(
            {
                "card_id": c.id,
                "student_id": str(c.student_id),
                "roll_no": roll,
                "name": c.student.full_name,
                "subjects": snap.get("subjects", []),
                "overall_pct": snap.get("overallPct", 0),
                "overall_grade": snap.get("overallGrade", "-"),
                "rank": snap.get("rank"),
                "total_students": snap.get("totalStudents", 0),
                "attendance_pct": snap.get("attendancePct", 0),
                "teacher_remark": snap.get("teacherRemark", ""),
                "principal_remark": snap.get("principalRemark") or "",
                "pdf_url": c.pdf_url or None,
                "pdf_published": c.pdf_published_at is not None,
            }
        )
    rows.sort(key=lambda r: (r["roll_no"] is None, r["roll_no"] or 0, r["name"]))
    return rows


def _roll(raw: str) -> int | None:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@transaction.atomic
def generate_pdfs(section: Section, term: str, remarks: dict[str, str]) -> dict:
    """Apply optional principal remarks, then render + store a PDF per card.
    ``remarks`` maps studentId (str) -> remark text."""
    class_name = section.class_obj.name
    section_name = section.name
    generated = 0
    for card in _published_cards(section, term).select_related("student"):
        snap = dict(card.data_snapshot or {})
        remark = remarks.get(str(card.student_id))
        if remark is not None:
            snap["principalRemark"] = remark
            card.data_snapshot = snap
        card.pdf_url = generate_and_store_report_card(
            card, class_name=class_name, section_name=section_name
        )
        card.save(update_fields=["data_snapshot", "pdf_url", "updated_at"])
        generated += 1
    return {"generated": generated}


@transaction.atomic
def publish_pdfs(section: Section, term: str) -> dict:
    """Make generated PDFs visible to parents (sets pdf_published_at)."""
    now = timezone.now()
    published = 0
    for card in _published_cards(section, term).exclude(pdf_url=""):
        card.pdf_published_at = now
        card.save(update_fields=["pdf_published_at", "updated_at"])
        published += 1
    return {"published": published}
