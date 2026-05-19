"""Fees: structures, per-student assignment, payments, receipts.

All monetary fields are PositiveBigIntegerField paise — never float.
Status on StudentFee + StudentFeeComponent is derived from payment
allocations and component due dates; recompute happens inside the
same transaction that mutates either side.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import TenantScopedModel


class FeeStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PARTIAL = "partial", "Partial"
    PAID = "paid", "Paid"
    OVERDUE = "overdue", "Overdue"


class PaymentMode(models.TextChoices):
    CASH = "cash", "Cash"
    CHEQUE = "cheque", "Cheque"
    BANK_TRANSFER = "bank_transfer", "Bank transfer"
    ONLINE = "online", "Online"  # placeholder for future gateway integration


# --- Structure side ---------------------------------------------------------

class FeeStructure(TenantScopedModel):
    """A reusable fee template for one (academic_year, class).

    Once applied to a class, edits to components should be done carefully —
    we don't auto-propagate changes to already-applied StudentFees.
    """

    academic_year = models.ForeignKey(
        "schools.AcademicYear", on_delete=models.PROTECT, related_name="fee_structures"
    )
    class_obj = models.ForeignKey(
        "academics.Class", on_delete=models.PROTECT, related_name="fee_structures"
    )
    name = models.CharField(max_length=120)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "fee_structures"
        constraints = [
            models.UniqueConstraint(
                fields=["school", "academic_year", "class_obj", "name"],
                name="uniq_fee_structure",
            ),
        ]
        ordering = ["class_obj__display_order", "name"]


class FeeComponent(TenantScopedModel):
    fee_structure = models.ForeignKey(
        FeeStructure, on_delete=models.CASCADE, related_name="components"
    )
    name = models.CharField(max_length=80)
    amount_paise = models.PositiveBigIntegerField()
    due_date = models.DateField()
    is_optional = models.BooleanField(default=False)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "fee_components"
        constraints = [
            models.UniqueConstraint(
                fields=["fee_structure", "name"], name="uniq_component_per_structure"
            ),
        ]
        ordering = ["display_order", "id"]


# --- Student-fee side -------------------------------------------------------

class StudentFee(TenantScopedModel):
    """One per (student, fee_structure). final = total - discount.
    paid is recomputed from the sum of non-voided FeePayment.total_amount."""

    student = models.ForeignKey(
        "people.Student", on_delete=models.CASCADE, related_name="fees"
    )
    fee_structure = models.ForeignKey(
        FeeStructure, on_delete=models.PROTECT, related_name="student_fees"
    )
    academic_year = models.ForeignKey(
        "schools.AcademicYear", on_delete=models.PROTECT, related_name="student_fees"
    )

    total_paise = models.PositiveBigIntegerField(default=0)
    discount_paise = models.PositiveBigIntegerField(default=0)
    final_paise = models.PositiveBigIntegerField(default=0)
    paid_paise = models.PositiveBigIntegerField(default=0)
    discount_reason = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=16, choices=FeeStatus.choices, default=FeeStatus.PENDING)

    class Meta:
        db_table = "student_fees"
        constraints = [
            models.UniqueConstraint(
                fields=["student", "fee_structure"], name="uniq_student_fee_per_structure"
            ),
        ]
        indexes = [
            models.Index(fields=["school", "status"]),
            models.Index(fields=["academic_year", "status"]),
        ]


class StudentFeeComponent(TenantScopedModel):
    """Per-student copy of a FeeComponent. ``applied_amount`` defaults to
    the component's amount but can be overridden (e.g. partial scholarship
    on a specific component). ``is_applicable=False`` means the student
    isn't charged this component at all (e.g. transport-optional)."""

    student_fee = models.ForeignKey(
        StudentFee, on_delete=models.CASCADE, related_name="components"
    )
    fee_component = models.ForeignKey(
        FeeComponent, on_delete=models.PROTECT, related_name="student_components"
    )
    applied_paise = models.PositiveBigIntegerField()
    paid_paise = models.PositiveBigIntegerField(default=0)
    is_applicable = models.BooleanField(default=True)
    status = models.CharField(max_length=16, choices=FeeStatus.choices, default=FeeStatus.PENDING)

    class Meta:
        db_table = "student_fee_components"
        constraints = [
            models.UniqueConstraint(
                fields=["student_fee", "fee_component"], name="uniq_student_fee_component"
            ),
        ]
        ordering = ["fee_component__display_order"]


# --- Payment side -----------------------------------------------------------

class ReceiptCounter(models.Model):
    """Per-school, per-academic-year monotonic counter for receipt numbers.
    Locked via select_for_update inside the payment transaction so concurrent
    payment recordings can't collide.
    """

    school = models.ForeignKey("schools.School", on_delete=models.CASCADE, related_name="receipt_counters")
    academic_year_label = models.CharField(max_length=20)
    next_number = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "receipt_counters"
        constraints = [
            models.UniqueConstraint(
                fields=["school", "academic_year_label"], name="uniq_receipt_counter"
            ),
        ]


class FeePayment(TenantScopedModel):
    """Header for a payment. Per-component allocations live in
    FeePaymentComponent. Voided rows stay in the table for audit — we
    never delete; ``voided_at`` flips the row out of all running totals."""

    student_fee = models.ForeignKey(
        StudentFee, on_delete=models.PROTECT, related_name="payments"
    )
    total_paise = models.PositiveBigIntegerField()
    payment_mode = models.CharField(max_length=20, choices=PaymentMode.choices)
    reference_number = models.CharField(max_length=80, blank=True)
    paid_on = models.DateField()
    received_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="payments_received"
    )
    receipt_number = models.CharField(max_length=40, unique=True)
    receipt_pdf_url = models.URLField(blank=True)
    notes = models.TextField(blank=True)

    voided_at = models.DateTimeField(null=True, blank=True, db_index=True)
    voided_reason = models.CharField(max_length=200, blank=True)
    voided_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments_voided",
    )

    class Meta:
        db_table = "fee_payments"
        indexes = [
            models.Index(fields=["school", "-paid_on"]),
            models.Index(fields=["student_fee", "-paid_on"]),
        ]
        ordering = ["-paid_on", "-id"]

    @property
    def is_voided(self) -> bool:
        return self.voided_at is not None


class FeePaymentComponent(TenantScopedModel):
    """Allocates a portion of a FeePayment against a StudentFeeComponent.
    Sum of allocations on a non-voided payment must equal payment.total_paise."""

    payment = models.ForeignKey(
        FeePayment, on_delete=models.CASCADE, related_name="allocations"
    )
    student_fee_component = models.ForeignKey(
        StudentFeeComponent, on_delete=models.PROTECT, related_name="payment_allocations"
    )
    amount_paise = models.PositiveBigIntegerField()

    class Meta:
        db_table = "fee_payment_components"
        indexes = [models.Index(fields=["payment"]), models.Index(fields=["student_fee_component"])]
