"""Schemas for fees endpoints. All money fields are integer paise."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field, field_validator

from apps.core.schemas import CamelSchema, Paginated

# --- Structures -------------------------------------------------------------

class FeeComponentIn(CamelSchema):
    name: str = Field(min_length=1, max_length=80)
    amount_paise: int = Field(ge=1)
    due_date: date
    is_optional: bool = False
    display_order: int = 0


class FeeComponentOut(CamelSchema):
    id: int
    name: str
    amount_paise: int
    due_date: date
    is_optional: bool
    display_order: int


class FeeStructureCreateRequest(CamelSchema):
    academic_year_id: int
    class_id: int
    name: str = Field(min_length=1, max_length=120)
    components: list[FeeComponentIn] = Field(min_length=1)


class FeeSectionStatusOut(CamelSchema):
    """How far a structure has been applied to one section of its class."""

    section_id: int
    name: str
    class_teacher_name: str | None = None
    student_count: int
    applied_count: int


class FeeStructureOut(CamelSchema):
    id: int
    name: str
    academic_year_id: int
    academic_year_label: str
    class_id: int
    class_name: str
    applied_at: datetime | None
    components: list[FeeComponentOut]
    # Populated only on the detail endpoint (per-section apply status).
    sections: list[FeeSectionStatusOut] = []


# --- Student fees -----------------------------------------------------------

class StudentFeeComponentOut(CamelSchema):
    id: int
    fee_component_id: int
    name: str
    applied_paise: int
    paid_paise: int
    is_applicable: bool
    is_optional: bool
    due_date: date
    status: str


class StudentFeeOut(CamelSchema):
    id: int
    student_id: int
    student_name: str
    admission_number: str
    class_name: str | None
    section_name: str | None
    academic_year_label: str
    structure_name: str
    total_paise: int
    discount_paise: int
    final_paise: int
    paid_paise: int
    outstanding_paise: int
    discount_reason: str
    status: str
    components: list[StudentFeeComponentOut]


class DiscountRequest(CamelSchema):
    discount_paise: int = Field(ge=0)
    reason: str = ""


class ToggleComponentRequest(CamelSchema):
    is_applicable: bool


class ApplyStructureRequest(CamelSchema):
    """Optional per-section filter. Omit or empty list = apply to all sections."""

    section_ids: list[int] = []


class ApplyStructureResponse(CamelSchema):
    created: int
    skipped: int
    total_students: int


# --- Payments ---------------------------------------------------------------

class PaymentAllocationIn(CamelSchema):
    component_id: int  # StudentFeeComponent.id
    amount_paise: int = Field(ge=1)


class PaymentCreateRequest(CamelSchema):
    student_fee_id: int
    paid_on: date
    payment_mode: str
    reference_number: str = ""
    notes: str = ""
    allocations: list[PaymentAllocationIn] = Field(min_length=1)

    @field_validator("payment_mode")
    @classmethod
    def _mode_known(cls, v: str) -> str:
        from apps.fees.models import PaymentMode

        if v not in PaymentMode.values:
            raise ValueError(f"must be one of {PaymentMode.values}")
        return v


class PaymentAllocationOut(CamelSchema):
    component_id: int
    component_name: str
    amount_paise: int


class PaymentOut(CamelSchema):
    id: int
    receipt_number: str
    student_fee_id: int
    student_id: int
    student_name: str
    total_paise: int
    payment_mode: str
    reference_number: str
    paid_on: date
    received_by_name: str | None
    notes: str
    receipt_pdf_url: str
    voided_at: datetime | None
    voided_reason: str
    allocations: list[PaymentAllocationOut]


class PaymentListOut(Paginated[PaymentOut]):
    pass


class VoidPaymentRequest(CamelSchema):
    reason: str = Field(min_length=1, max_length=200)


# --- Dues + dashboard -------------------------------------------------------

class DuesRowOut(CamelSchema):
    student_fee_id: int
    student_id: int
    student_name: str
    admission_number: str
    class_name: str
    section_name: str | None
    total_paise: int
    final_paise: int
    paid_paise: int
    outstanding_paise: int
    status: str


class DuesTotals(CamelSchema):
    outstanding_paise: int = 0


class DuesListOut(Paginated[DuesRowOut]):
    totals: DuesTotals


class SectionRollupOut(CamelSchema):
    section_id: int
    section_name: str
    class_id: int
    class_name: str
    display_order: int
    student_count: int
    expected_paise: int
    collected_paise: int
    outstanding_paise: int
    paid_count: int
    partial_count: int
    pending_count: int
    overdue_count: int


class FeesRollupTotals(CamelSchema):
    expected_paise: int = 0
    collected_paise: int = 0
    outstanding_paise: int = 0
    paid_count: int = 0
    partial_count: int = 0
    pending_count: int = 0
    overdue_count: int = 0


class FeesRollupOut(CamelSchema):
    sections: list[SectionRollupOut]
    totals: FeesRollupTotals
