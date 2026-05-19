# Skooly Backend Progress

## Current Status

- Modules 1–4 + 7 complete (Module 5 on hold, Module 6 pending)
- 62 endpoints · 116 tests passing · ruff clean

## Modules

- [x] **Module 1: Foundation** — auth, school, academic year, tenant infrastructure
- [x] **Module 2: People & Structure** — full CRUD, bulk import, photo upload
- [x] **Module 3: Attendance (read-only)** — 4 endpoints, bulk dashboard rollup
- [x] **Module 4: Tests & Scores (read-only)** — 4 endpoints, ~3 tests per (section, subject) seeded
- [ ] Module 5: WhatsApp Integration — **on hold**
- [ ] Module 6: Report Cards
- [x] **Module 7: Fees** — full CRUD + payments + receipts + dues
- [ ] Module 8: Analytics
- [ ] Module 9: Parent Web View
- [ ] Module 10: Polish

## Module 7 — what shipped

### Endpoints (13 new, 62 total)

**Structures**
- `GET /fee-structures` — list, filter by year/class
- `POST /fee-structures` — create with nested components
- `GET /fee-structures/{id}` — detail
- `POST /fee-structures/{id}/apply` — fan-out to class roster (idempotent)

**Student fees**
- `GET /students/{id}/fees` — fee detail with components
- `PATCH /student-fees/{id}/discount` — apply discount with reason
- `POST /student-fees/{id}/components/{component_id}/toggle` — toggle optional component

**Payments**
- `GET /payments` — paginated ledger, filterable, optional `includeVoided`
- `POST /payments` — record with **component-level allocation**, auto receipt #, PDF
- `GET /payments/{id}` — detail
- `POST /payments/{id}/void` — soft-void with reason, reverses allocations + status

**Dashboard**
- `GET /fees/dues` — paginated dues, totals
- `GET /fees/rollup` — per-section collection summary

### Data model

- `FeeStructure` (academic_year, class, name) → `FeeComponent[]` (name, amount_paise, due_date, is_optional)
- `StudentFee` (student, structure, total, discount, final, paid, status) → `StudentFeeComponent[]` (applied_paise, paid_paise, is_applicable, status)
- `FeePayment` (header: total_paise, mode, paid_on, receipt_number, voided fields) → `FeePaymentComponent[]` (allocation per component)
- `ReceiptCounter` — per-school, per-academic-year monotonic counter, locked via `select_for_update` inside the payment transaction

**All money fields are `PositiveBigIntegerField` paise.** Never float. A structural test (`test_no_floats_in_money_fields`) asserts this.

### Status state machine

`StudentFee.status` derived from components inside the same transaction that mutates any payment/discount/component toggle:

- **paid**: `paid >= final`
- **partial**: `paid > 0`, nothing overdue
- **overdue**: any applicable component past its due date (regardless of partial-payment state)
- **pending**: nothing paid, nothing overdue yet

Recompute also runs nightly via `recompute_overdue_all` (drift-correction; safe to run any time).

### Receipt PDF

- WeasyPrint template at `apps/fees/receipt_pdf.py` — A5 layout, school branding via `primary_color` from `School`, "VOID" watermark when applicable
- Uploaded via Django `default_storage` (local in dev, R2 in prod via `USE_R2=True` config flag — no code change)
- TODO comment: flip `USE_R2=True` and verify the URLs are reachable behind a signed CDN when first prod school onboards

### Seed

- One structure per class for the current AY (Class 1: ₹15k total, Class 10: ₹71.5k total — realistic AP State Board ranges)
- Components: Tuition, Books & Stationery, Lab/Computer/Board Exam (class-appropriate), Transport optional
- Applied to all 660 students
- ~60% of students have a payment (mix of full + partial); ~10% completely overdue
- **Demo numbers**: 10 structures · 660 student fees · 401 payments · ₹2.18 crore expected, ₹94 lakh collected, ₹1.24 crore outstanding

### Tests (21 new, 116 total)

- Apply structure: idempotent re-apply, status=pending vs overdue based on due dates, optional component defaults to non-applicable
- Payment math: full payment → paid; partial → partial; overpay rejected; negative amount rejected
- Voiding: reverses allocations, recomputes status, second void rejected
- Receipt numbering: sequential within (school, AY), counter advances
- Discounts: reduces final, exceeding total rejected, paid-after-discount marks paid
- Permissions: teacher cannot create structure or record payment
- Cross-tenant: all 404s on structure / payment / void
- Dues: only unpaid students; drops out when fully paid
- **Structural**: every money field is `PositiveBigIntegerField`

### Deferred to follow-up (online payments workstream)

- Razorpay payment links (Tier 1 — ~2 days, blocks on per-school KYC)
- Razorpay Checkout embed (Tier 2)
- UPI mandates / subscriptions (Tier 3)

## Frontend wiring

All admin fees pages on real API:

- `/admin/fees` — overview with stats tiles + section-wise collection bars
- `/admin/fees/structures` — list per class/year with totals + applied status
- `/admin/fees/apply` — pick structure → preview → apply, with idempotent feedback
- `/admin/fees/record-payment` — student search → fee detail → per-component allocation form with pre-filled remaining amounts
- `/admin/fees/history` — ledger with search, mode filter, "Show voided" toggle, void dialog with reason
- `/admin/fees/dues` — dues report with class/status filters, "Record" shortcut per row
- Student detail **Fees tab** — full fee detail + components + payment history

Money helpers in `src/lib/money.ts` (paise ↔ rupees, never float arithmetic for storage).

## Other modules — quick recap

- **Module 1**: auth + tenant infra
- **Module 2**: full students/teachers CRUD, bulk Excel import, photo upload via `default_storage`
- **Module 3**: read-only attendance (4 endpoints, bulk roll-up, redesigned dashboard)
- **Module 4**: read-only tests + scores (4 endpoints, 450 seeded tests with 12k scores)

## Demo flow (~3 minutes)

```bash
cd ~/git/skooly && docker compose up -d --build api
cd ~/git/skooly-stride && bun run dev
```

Login: `+919876543210` / `demo1234`

1. **Fees overview** → see ₹2.18 cr expected, ₹94 lakh collected, 489 overdue students, section-wise progress bars
2. **Structures** → 10 structures, one per class
3. **Apply** → preview Class 6 structure (5 components), can re-apply (idempotent → "0 created, 27 skipped")
4. **Dues** → 489 students with outstanding fees, filter by class/status
5. **Record payment** → search student → see remaining per component → submit → toast with receipt #
6. **History** → see the new receipt at the top → void with reason → row goes opacity-60 and rollup updates
7. **Student detail → Fees tab** → see the full breakdown + that student's payments

## Open / pending

- **Uncommitted**: Module 7 (this one). One backend commit + one frontend commit.
- **Backlog** (see `docs/backlog.md`):
  - **P2** Mid-year admission pro-rating
  - **P3** Revisit receipt number format (per-school customization)
- **Discount approval workflow**: parked (currently any admin can apply any discount, audit-logged)
- **Online payment gateway**: separate workstream after Module 6 + Module 5
- **Module 5 (WhatsApp) on hold**: when it lands, fee reminders + receipt-sent + payment-confirmation templates will use the queue-and-dispatch pattern. Module 7 has no WhatsApp wiring yet.
- **Receipt PDF in seed**: skipped for volume reasons. PDFs generate on real payment recording; admins can regenerate later via a follow-up endpoint when added.

## Commands

```bash
uv run ruff check .         # clean
uv run pytest --tb=no -q    # 116 passing
uv run python manage.py seed_demo --reset
```
