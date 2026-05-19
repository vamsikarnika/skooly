"""Receipt PDF generation via WeasyPrint, stored via default_storage.

The HTML template is intentionally simple — schools' auditors care about
readable numbers and unique receipt IDs, not visual flair. School logo +
primary color give a basic brand surface.
"""

from __future__ import annotations

import secrets
from io import BytesIO
from pathlib import PurePosixPath

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from weasyprint import HTML

from apps.fees.models import FeePayment


def _rupees(paise: int) -> str:
    rupees = paise / 100
    return f"₹{rupees:,.2f}"


def _render_html(payment: FeePayment) -> str:
    school = payment.school
    sf = payment.student_fee
    student = sf.student
    structure = sf.fee_structure
    allocations = list(payment.allocations.select_related("student_fee_component__fee_component"))

    alloc_rows = "".join(
        f"""
        <tr>
          <td>{a.student_fee_component.fee_component.name}</td>
          <td class="num">{_rupees(a.amount_paise)}</td>
        </tr>
        """
        for a in allocations
    )

    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {{ size: A5 portrait; margin: 12mm; }}
  body {{ font-family: Helvetica, Arial, sans-serif; font-size: 10pt; color: #1a1a1a; }}
  .header {{ border-bottom: 2px solid {school.primary_color or "#1f4e79"}; padding-bottom: 10px; margin-bottom: 14px; }}
  .school-name {{ font-size: 16pt; font-weight: bold; color: {school.primary_color or "#1f4e79"}; }}
  .school-meta {{ font-size: 9pt; color: #555; }}
  .receipt-no {{ float: right; text-align: right; }}
  .receipt-no .num {{ font-family: monospace; font-size: 12pt; font-weight: bold; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
  th, td {{ padding: 4px 6px; border-bottom: 1px solid #ddd; text-align: left; }}
  th {{ background: #f4f4f4; font-size: 9pt; }}
  td.num, th.num {{ text-align: right; font-family: monospace; }}
  .grid {{ margin-bottom: 12px; }}
  .grid td {{ border: none; padding: 2px 6px; }}
  .grid .label {{ color: #666; width: 35%; }}
  .totals {{ margin-top: 10px; }}
  .totals .total-row td {{ border-top: 2px solid #1a1a1a; font-weight: bold; padding-top: 6px; }}
  .footer {{ margin-top: 18px; padding-top: 10px; border-top: 1px solid #ddd; font-size: 8.5pt; color: #666; }}
  .void {{
    position: fixed; top: 35mm; left: 18mm;
    transform: rotate(-25deg);
    font-size: 60pt; color: rgba(220, 38, 38, 0.18);
    font-weight: bold; letter-spacing: 4px;
  }}
</style>
</head>
<body>
  {'<div class="void">VOID</div>' if payment.is_voided else ''}
  <div class="header">
    <div class="receipt-no">
      <div class="school-meta">Receipt No.</div>
      <div class="num">{payment.receipt_number}</div>
    </div>
    <div class="school-name">{school.name}</div>
    <div class="school-meta">{school.address or ''}</div>
  </div>

  <table class="grid">
    <tr><td class="label">Student</td><td><strong>{student.first_name} {student.last_name}</strong></td></tr>
    <tr><td class="label">Admission No.</td><td>{student.admission_number}</td></tr>
    <tr><td class="label">Class / Section</td><td>{structure.class_obj.name}</td></tr>
    <tr><td class="label">Academic Year</td><td>{sf.academic_year.label}</td></tr>
    <tr><td class="label">Payment Mode</td><td>{payment.payment_mode.replace('_', ' ').title()}{f" — Ref: {payment.reference_number}" if payment.reference_number else ""}</td></tr>
    <tr><td class="label">Paid On</td><td>{payment.paid_on.strftime('%d %b %Y')}</td></tr>
  </table>

  <table>
    <thead>
      <tr>
        <th>Component</th>
        <th class="num">Amount</th>
      </tr>
    </thead>
    <tbody>
      {alloc_rows}
    </tbody>
    <tfoot>
      <tr class="total-row">
        <td>Total received</td>
        <td class="num">{_rupees(payment.total_paise)}</td>
      </tr>
    </tfoot>
  </table>

  {f'<div class="footer"><strong>Notes:</strong> {payment.notes}</div>' if payment.notes else ''}
  <div class="footer">
    {'<strong>VOIDED:</strong> ' + payment.voided_reason if payment.is_voided else 'This is a computer-generated receipt.'}
  </div>
</body>
</html>
"""


def generate_and_store_receipt(payment: FeePayment) -> str:
    """Render the receipt to PDF and upload via default_storage. Returns
    the resolved URL (works for local + S3/R2 the same way thanks to
    default_storage abstraction).

    TODO: when first prod school onboards, flip USE_R2=True and verify the
    returned URL is reachable behind a signed CDN.
    """
    html = _render_html(payment)
    pdf_bytes = BytesIO()
    HTML(string=html).write_pdf(target=pdf_bytes)

    nonce = secrets.token_hex(4)
    key = str(
        PurePosixPath("receipts")
        / str(payment.school_id)
        / f"{payment.receipt_number.replace('/', '_')}-{nonce}.pdf"
    )
    saved = default_storage.save(key, ContentFile(pdf_bytes.getvalue()))
    return default_storage.url(saved)
