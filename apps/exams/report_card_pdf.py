"""Report-card PDF generation via WeasyPrint, stored via default_storage.

A polished, school-branded A4 template — coloured header from the school's
primary colour + logo, KPI tiles, grade badges, a grade-scale legend and styled
remark/signature blocks. Filled from the report card's immutable
``data_snapshot``. Mirrors the storage pattern in apps/fees/receipt_pdf.py.
"""

from __future__ import annotations

import html
import secrets
from io import BytesIO
from pathlib import PurePosixPath

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from apps.exams.models import ReportCard

# AP/CBSE 10-point grade bands, used for the legend strip.
GRADE_SCALE = [
    ("A1", "91-100"),
    ("A2", "81-90"),
    ("B1", "71-80"),
    ("B2", "61-70"),
    ("C1", "51-60"),
    ("C2", "41-50"),
    ("D", "33-40"),
    ("E", "Below 33"),
]


def _esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""))


def _grade_color(grade: str | None) -> str:
    g = (grade or "").upper()
    if g in ("A1", "A2"):
        return "#15803d"  # green
    if g in ("B1", "B2"):
        return "#1d4ed8"  # blue
    if g in ("C1", "C2"):
        return "#b45309"  # amber
    if g in ("D", "E"):
        return "#b91c1c"  # red
    return "#64748b"  # slate


def _subject_rows(subjects: list[dict]) -> str:
    rows = []
    for i, s in enumerate(subjects):
        marks = s.get("marks")
        grade = s.get("grade") or "—"
        gc = _grade_color(s.get("grade"))
        zebra = "background:#f8fafc;" if i % 2 else ""
        rows.append(
            f"""
        <tr style="{zebra}">
          <td class="subj">{_esc(s.get("name"))}</td>
          <td class="num">{_esc(marks) if marks is not None else "—"}</td>
          <td class="num muted">{_esc(s.get("maxMarks"))}</td>
          <td class="center"><span class="badge" style="color:{gc};background:{gc}1f;">{_esc(grade)}</span></td>
        </tr>"""
        )
    return "".join(rows)


def _legend() -> str:
    chips = "".join(
        f'<span class="chip"><b style="color:{_grade_color(g)};">{g}</b> {rng}</span>'
        for g, rng in GRADE_SCALE
    )
    return f'<div class="legend"><span class="legend-label">Grading scale</span>{chips}</div>'


def _brand_mark(school) -> str:  # type: ignore[no-untyped-def]
    if school.logo_url:
        return (
            f'<div class="logo"><img src="{_esc(school.logo_url)}" alt="" '
            f'style="max-height:52px;max-width:96px;object-fit:contain;" /></div>'
        )
    initial = _esc((school.name or "S").strip()[:1].upper())
    return f'<div class="monogram">{initial}</div>'


def _render_html(card: ReportCard, *, class_name: str, section_name: str) -> str:
    school = card.school
    student = card.student
    snap = card.data_snapshot or {}
    color = school.primary_color or "#2563eb"

    overall_pct = snap.get("overallPct", 0)
    overall_grade = snap.get("overallGrade", "—")
    rank = snap.get("rank")
    total = snap.get("totalStudents")
    rank_txt = f"{rank}<span class='of'> / {total}</span>" if rank and total else "—"
    attendance = snap.get("attendancePct")
    teacher_remark = snap.get("teacherRemark") or "—"
    principal_remark = snap.get("principalRemark") or "—"
    full_name = f"{student.first_name} {student.last_name}".strip()

    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {{ size: A4 portrait; margin: 0; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: Helvetica, Arial, sans-serif; color: #0f172a; font-size: 10.5pt; }}
  .sheet {{ padding: 0 0 18mm; }}

  /* Header band */
  .band {{
    background: linear-gradient(115deg, {color} 0%, {color}cc 100%);
    color: #fff; padding: 16mm 14mm 11mm; display: flex; align-items: center; gap: 14px;
  }}
  .logo, .monogram {{
    width: 60px; height: 60px; border-radius: 14px; background: rgba(255,255,255,.18);
    display: flex; align-items: center; justify-content: center; flex: none;
  }}
  .monogram {{ font-size: 26pt; font-weight: 800; color: #fff; }}
  .logo {{ background: #fff; }}
  .band .school-name {{ font-size: 19pt; font-weight: 800; letter-spacing: .2px; }}
  .band .school-meta {{ font-size: 9pt; opacity: .92; margin-top: 2px; }}
  .band .right {{ margin-left: auto; text-align: right; }}
  .band .tag {{
    display: inline-block; background: rgba(255,255,255,.2); border: 1px solid rgba(255,255,255,.35);
    padding: 4px 12px; border-radius: 999px; font-size: 9pt; font-weight: 700; letter-spacing: 1.5px;
  }}
  .band .term {{ font-size: 14pt; font-weight: 800; margin-top: 6px; }}
  .band .year {{ font-size: 9pt; opacity: .92; }}

  .body {{ padding: 0 14mm; }}

  /* Student panel */
  .student {{
    margin-top: -7mm; background: #fff; border: 1px solid #e8edf3; border-radius: 14px;
    padding: 12px 16px; display: flex; align-items: center; gap: 14px;
    box-shadow: 0 6px 18px rgba(15,23,42,.06);
  }}
  .avatar {{
    width: 46px; height: 46px; border-radius: 50%; background: {color}1f; color: {color};
    font-weight: 800; font-size: 18pt; display: flex; align-items: center; justify-content: center; flex: none;
  }}
  .student .name {{ font-size: 14pt; font-weight: 800; }}
  .student .sub {{ font-size: 9pt; color: #64748b; margin-top: 1px; }}
  .student .meta {{ margin-left: auto; text-align: right; font-size: 9pt; color: #475569; }}
  .student .meta b {{ color: #0f172a; }}

  /* KPI tiles */
  .kpis {{ display: flex; gap: 10px; margin-top: 14px; }}
  .kpi {{ flex: 1; border: 1px solid #e8edf3; border-radius: 12px; padding: 10px 12px; text-align: center; }}
  .kpi .label {{ font-size: 7.5pt; text-transform: uppercase; letter-spacing: .8px; color: #94a3b8; }}
  .kpi .value {{ font-size: 18pt; font-weight: 800; margin-top: 2px; line-height: 1; }}
  .kpi .of {{ font-size: 9pt; color: #94a3b8; font-weight: 600; }}
  .kpi.accent {{ background: {color}0f; border-color: {color}33; }}
  .kpi.accent .value {{ color: {color}; }}

  /* Marks table */
  table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
  thead th {{
    background: #0f172a; color: #fff; font-size: 8.5pt; text-transform: uppercase; letter-spacing: .6px;
    padding: 8px 10px; text-align: left;
  }}
  thead th.num, thead th.center {{ text-align: center; }}
  tbody td {{ padding: 8px 10px; border-bottom: 1px solid #eef2f7; }}
  td.subj {{ font-weight: 600; }}
  td.num {{ text-align: right; font-family: 'DejaVu Sans Mono', monospace; }}
  td.center {{ text-align: center; }}
  td.muted {{ color: #94a3b8; }}
  .badge {{ display: inline-block; min-width: 30px; padding: 2px 8px; border-radius: 999px; font-weight: 700; font-size: 9pt; }}
  tfoot td {{ padding: 9px 10px; border-top: 2px solid #0f172a; font-weight: 800; }}
  tfoot .lbl {{ text-transform: uppercase; letter-spacing: .6px; font-size: 9pt; }}

  /* Legend */
  .legend {{ margin-top: 10px; font-size: 8pt; color: #64748b; }}
  .legend-label {{ text-transform: uppercase; letter-spacing: .6px; margin-right: 8px; color: #94a3b8; }}
  .chip {{ display: inline-block; border: 1px solid #e8edf3; border-radius: 999px; padding: 1px 8px; margin: 0 4px 4px 0; }}

  /* Remarks */
  .remarks {{ display: flex; gap: 10px; margin-top: 16px; }}
  .remark {{ flex: 1; border: 1px solid #e8edf3; border-radius: 12px; padding: 10px 12px; }}
  .remark .who {{ font-size: 7.5pt; text-transform: uppercase; letter-spacing: .7px; color: #94a3b8; }}
  .remark .text {{ margin-top: 4px; font-size: 9.5pt; min-height: 26px; }}

  /* Signatures + footer */
  .signs {{ display: flex; justify-content: space-between; margin-top: 26px; }}
  .sign {{ text-align: center; width: 30%; }}
  .sign .line {{ border-top: 1px solid #94a3b8; margin-bottom: 4px; }}
  .sign .role {{ font-size: 8.5pt; color: #64748b; }}
  .footer {{ margin-top: 18px; text-align: center; font-size: 7.5pt; color: #b6c0cd; }}
  .footer b {{ color: {color}; }}
</style>
</head>
<body>
<div class="sheet">
  <div class="band">
    {_brand_mark(school)}
    <div>
      <div class="school-name">{_esc(school.name)}</div>
      <div class="school-meta">{_esc(school.address)}</div>
      <div class="school-meta">{_esc(school.get_board_display())}</div>
    </div>
    <div class="right">
      <span class="tag">REPORT CARD</span>
      <div class="term">{_esc(snap.get("term"))}</div>
      <div class="year">Academic Year {_esc(snap.get("academicYear"))}</div>
    </div>
  </div>

  <div class="body">
    <div class="student">
      <div class="avatar">{_esc(full_name[:1].upper())}</div>
      <div>
        <div class="name">{_esc(full_name)}</div>
        <div class="sub">Admission No. {_esc(student.admission_number)}</div>
      </div>
      <div class="meta">
        <div>Class <b>{_esc(class_name)} · {_esc(section_name)}</b></div>
        <div>Issued <b>{_esc(snap.get("issueDate"))}</b></div>
      </div>
    </div>

    <div class="kpis">
      <div class="kpi accent">
        <div class="label">Overall</div>
        <div class="value">{_esc(overall_pct)}%</div>
      </div>
      <div class="kpi">
        <div class="label">Grade</div>
        <div class="value" style="color:{_grade_color(overall_grade)};">{_esc(overall_grade)}</div>
      </div>
      <div class="kpi">
        <div class="label">Class Rank</div>
        <div class="value">{rank_txt}</div>
      </div>
      <div class="kpi">
        <div class="label">Attendance</div>
        <div class="value">{_esc(attendance)}<span class="of">%</span></div>
      </div>
    </div>

    <table>
      <thead>
        <tr><th>Subject</th><th class="num">Marks</th><th class="num">Max</th><th class="center">Grade</th></tr>
      </thead>
      <tbody>
        {_subject_rows(snap.get("subjects", []))}
      </tbody>
      <tfoot>
        <tr>
          <td class="lbl">Overall</td>
          <td class="num">{_esc(overall_pct)}%</td>
          <td></td>
          <td class="center"><span class="badge" style="color:{_grade_color(overall_grade)};background:{_grade_color(overall_grade)}1f;">{_esc(overall_grade)}</span></td>
        </tr>
      </tfoot>
    </table>

    {_legend()}

    <div class="remarks">
      <div class="remark">
        <div class="who">Class Teacher's Remark</div>
        <div class="text">{_esc(teacher_remark)}</div>
      </div>
      <div class="remark">
        <div class="who">Principal's Remark</div>
        <div class="text">{_esc(principal_remark)}</div>
      </div>
    </div>

    <div class="signs">
      <div class="sign"><div class="line"></div><div class="role">Class Teacher</div></div>
      <div class="sign"><div class="line"></div><div class="role">Principal</div></div>
      <div class="sign"><div class="line"></div><div class="role">Parent / Guardian</div></div>
    </div>

    <div class="footer">Generated by <b>Skooly</b> · {_esc(snap.get("issueDate"))}</div>
  </div>
</div>
</body>
</html>
"""


def generate_and_store_report_card(
    card: ReportCard, *, class_name: str, section_name: str
) -> str:
    """Render the card to a branded PDF, upload via default_storage, return URL."""
    html_str = _render_html(card, class_name=class_name, section_name=section_name)
    pdf_bytes = BytesIO()
    from weasyprint import HTML  # lazy: pulls in system libs we don't want at import

    HTML(string=html_str).write_pdf(target=pdf_bytes)

    nonce = secrets.token_hex(4)
    key = str(PurePosixPath("report-cards") / str(card.school_id) / f"{card.id}-{nonce}.pdf")
    saved = default_storage.save(key, ContentFile(pdf_bytes.getvalue()))
    return default_storage.url(saved)
