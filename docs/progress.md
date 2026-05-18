# Skooly Backend Progress

## Current Status

- Modules 1–4 complete (Module 3 & 4 read-only; teacher app will own POSTs)
- 49 endpoints · 95 tests passing · ruff clean

## Modules

- [x] **Module 1: Foundation** — auth, school, academic year, tenant infrastructure
- [x] **Module 2: People & Structure** — full CRUD, bulk import, photo upload via Django default_storage
- [x] **Module 3: Attendance (read-only)** — 4 endpoints, bulk dashboard rollup, redesigned UI
- [x] **Module 4: Tests & Scores (read-only)** — 4 endpoints, ~3 tests per (section, subject) seeded, published-only filter
- [ ] Module 5: WhatsApp Integration
- [ ] Module 6: Report Cards
- [ ] Module 7: Fees
- [ ] Module 8: Analytics
- [ ] Module 9: Parent Web View
- [ ] Module 10: Polish

## Module 4 — what shipped

### Endpoints (4 new, 49 total)

- `GET /tests` — paginated, filters: `sectionId`, `classId`, `subjectId`, `testType`, `from`, `to`. **Published only** (drafts not exposed)
- `GET /tests/{id}` — test meta + roster + every student's score (or null + is_absent flag) + computed stats (avg, max, min, scored/absent counts)
- `GET /sections/{id}/tests` — chronological list for one section
- `GET /students/{id}/scores?from=&to=` — history grouped by subject with per-subject average %

### Data model

- `Test` (TenantScoped): section, subject, name, test_type (FA1–FA4, SA1, SA2, OTHER), test_date, max_marks, created_by, published_at (null = draft)
- `TestScore` (TenantScoped): test, student, marks_obtained (Decimal 5,2), is_absent, entered_by, entered_at. Unique on `(test, student)`

### Seed

- ~3 published tests per (section, subject) over the last 90 days
- Mix of FA1, FA2, SA1 (50 / 50 / 100 marks)
- Per-student ability offset (gaussian, sd 0.08) so subject averages stay realistic across tests
- ~5% absent rate
- **Demo numbers**: 450 tests · 12,375 scores

### Tests (11 new, 95 total)

- Drafts excluded from `GET /tests`
- Draft `GET /tests/{id}` returns 404
- Stats math: 40+30+50 mean=40, absent excluded
- Roster includes unscored students (status=null)
- Cross-tenant isolation: list, detail, section-tests, student-scores all 404
- Section-tests filtering scopes correctly
- Student history: drafts excluded, average % computed
- Absent excluded from student average
- Auth required

### Deferred to teacher-app build

- `POST /tests` (create draft)
- `POST /tests/{id}/scores` (bulk paste-from-Excel)
- `POST /tests/{id}/publish` (with WhatsApp queue writes for Module 5)
- `POST /tests/{id}/unpublish` (admin only)
- Edit window enforcement

## Module 3 — quick recap

- `GET /attendance/sections?date=` — single bulk endpoint for dashboard (1 API call, 4 DB queries regardless of section count; 6ms for 24 sections in the demo)
- `GET /sections/{id}/attendance?date=` — per-section roster + marks
- `GET /sections/{id}/attendance/summary?from=&to=` — per-student attendance %
- `GET /students/{id}/attendance?from=&to=` — student history

### Attendance UI redesign

Replaced the flat-grid-of-cards with a dense list grouped by class, top stats strip (sections marked, not yet marked, absent count), search + filter chips (All / Unmarked / With absences), date picker. Scales to 100+ sections.

## Frontend pages on real API

- `/login`, `/signup`
- `/admin/students` + detail (Profile, Attendance, Marks tabs all live)
- `/admin/teachers` + detail
- `/admin/attendance` (redesigned) + section detail
- `/admin/tests` + detail (matching density-first design as attendance)

Auth guard: `beforeLoad` on `/admin` and `/teacher` redirect to `/login?redirect=…` when no token; client-side handler on 401 (with refresh failure) also bounces to login.

## Demo flow

```bash
cd ~/git/skooly && docker compose up -d --build api
cd ~/git/skooly-stride && bun run dev
```

Login: `+919876543210` / `demo1234`

End-to-end you can now see:
1. **Students** → list, add, edit, transfer, withdraw, bulk import, export
2. **Teachers** → list, add, edit, mark inactive
3. **Attendance** → dashboard with stats, drill into section/date, student history
4. **Tests** → 450 tests across sections/subjects, filter by class/subject/type, drill into a test for ranked scores + class average + pass rate
5. **Student detail** → Profile, Attendance (60-day history with %), Marks (grouped by subject with per-subject avg %)

## Open / pending

- **Uncommitted**: Modules 3 (attendance), 3.5 (UX redesign), auth-redirect fix, Module 4 (this one). 4–5 logical commits worth.
- **Backend exists, no UI yet**: Classes admin CRUD; photo upload widget.
- **Stub**: Student-detail Edit form save handler (still toasts).
- **Phone uniqueness**: globally unique (Django auth requirement). Revisit if teachers need multi-school accounts.
- **Test naming uniqueness**: no constraint preventing two "FA1 · Unit Test · Math · Class 6-A · 2026-05-01" rows. Probably fine — tests are dated; rename if duplicate is intentional.

## Commands

```bash
uv run ruff check .        # clean
uv run pytest --tb=no -q   # 95 passing
uv run python manage.py seed_demo --reset  # regenerate everything
```
