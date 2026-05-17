# Skooly Backend Progress

## Current Status

- Module 1: complete
- **Module 2 (People & Structure): complete** — full CRUD for students, teachers, classes, sections, subjects, teacher assignments; bulk Excel import; Excel export; photo upload via Django default_storage (local in dev, R2 swap is a config flag).
- Module 3+ pending.

## Modules

- [x] Module 1: Foundation (auth, school, academic year, tenant infra)
- [x] Module 2: People & Structure
- [ ] Module 3: Attendance
- [ ] Module 4: Tests & Scores
- [ ] Module 5: WhatsApp Integration
- [ ] Module 6: Report Cards
- [ ] Module 7: Fees
- [ ] Module 8: Analytics
- [ ] Module 9: Parent Web View
- [ ] Module 10: Polish

## API Endpoints (41 total)

### Auth (`/api/v1/auth/`)
- POST signup, login, refresh, forgot-password, verify-otp, reset-password
- GET me (auth)

### Schools (`/api/v1/schools/`) — admin for writes
- GET/PATCH /current
- GET/POST /academic-years
- PATCH /academic-years/{id}

### People (`/api/v1/`) — admin for writes
- GET /students (paginated, filterable by classId/sectionId/status/q)
- POST /students — admin only
- POST /students/bulk-import — admin only, multipart .xlsx + dryRun flag
- GET /students/export — admin only, .xlsx download
- GET /students/{id}, PATCH, DELETE (soft → withdrawn)
- POST /students/{id}/transfer — preserves enrollment history
- POST /students/{id}/photo — multipart image
- GET /teachers (paginated)
- POST /teachers — admin only
- GET /teachers/{id}, PATCH, DELETE (soft → inactive)
- POST /teachers/{id}/photo

### Academics (`/api/v1/`) — admin for writes
- GET /classes (nested sections + student counts)
- POST /classes, PATCH /classes/{id}, DELETE /classes/{id} (blocked if sections exist)
- GET /sections/{id}, POST /sections, PATCH, DELETE (blocked if active enrollments)
- GET /subjects, POST /subjects, PATCH /subjects/{id}, DELETE /subjects/{id}
- POST /teacher-assignments, DELETE /teacher-assignments/{id}

OpenAPI captured at [docs/openapi.json](openapi.json).

## Tests

64 passing. Module 2 adds:

- **CRUD happy paths** for students, teachers, classes, sections, subjects, teacher assignments.
- **Tenant isolation on writes**: admin A cannot create-into / patch / delete / transfer / assign / etc. any resource in school B. Every cross-tenant attempt returns 404 (no existence leak).
- **Permission tests**: teacher role cannot use admin-only endpoints (create student, create teacher, create class, bulk import).
- **Bulk import edge cases**: dry-run validation, all-or-nothing commit (one bad row rejects the batch), duplicate admission numbers (within file + against DB), missing required columns, invalid gender, unknown class/section, blank rows skipped, teacher role forbidden.
- **Transfer flow**: preserves history (old enrollment marked `transferred`, new one `active`), rejects no-op transfer to same section, partial unique constraint enforces one active enrollment per (student, year).

## Photo storage

- All uploads go through Django's `default_storage` (`apps/core/storage.py`).
- Dev: `FileSystemStorage` → writes to `MEDIA_ROOT/uploads/<school_id>/<kind>/<owner_id>-<ts>-<nonce>.<ext>`; served by Django in DEBUG mode.
- Prod: set `USE_R2=True` + credentials → same calls hit Cloudflare R2.
- Pillow resizes to max 1024×1024 and re-encodes (JPEG q=85). Max 5 MB. Allowed: jpeg/png/webp.
- **TODO**: when first prod school onboards, flip `USE_R2=True` and verify CDN URLs. No code change required.

## Demo seed (unchanged from Module 1)

`docker compose up` → postgres + redis + Django auto-migrate + auto-seed.

- **School**: Vidya Bharati High School (Vijayawada, AP State Board)
- 10 classes, 24 sections, 18 teachers, 9 subjects, ~660 students
- **Admin login**: `+919876543210` / `demo1234`

`python manage.py seed_demo --reset` to wipe and recreate.

## Frontend wiring

Real-API pages:
- `/login`, `/signup`
- `/admin/students` — list with pagination, class/section/status filters, search; row actions: View / Edit / Transfer / Withdraw via dropdown
- `/admin/students/:id` — detail (Profile tab live; Attendance/Marks/Fees/Comms placeholders for their modules)
- `/admin/teachers` — list, add, edit, mark inactive
- `/admin/teachers/:id` — detail

Frontend components added:
- `components/students/StudentFormDialog.tsx` — create/edit
- `components/students/BulkImportDialog.tsx` — two-phase (validate → commit) with per-row error display
- `components/teachers/TeacherFormDialog.tsx` — create/edit

Pages still using mock data: attendance, fees, tests, classes detail, announcements, analytics, report cards. These migrate as their backend modules land.

## Open questions / known gaps

- **Classes admin CRUD UI**: not yet built — list page already shows live data from `GET /classes`, but creating/editing classes/sections from the UI hasn't been wired. Backend endpoints exist (`POST/PATCH/DELETE /classes` and `/sections`); building the UI is ~half a day. Deferred until needed.
- **Photo upload UI**: backend endpoint exists; no UI button yet. Add to student/teacher detail pages when needed.
- **Student detail edit**: the detail page has an Edit button that opens an inline form, but the save handler currently shows a toast and doesn't POST. Fix is to call `studentsApi.updateStudent` — added to the AddStudent dialog already, just needs to be reused.
- **Bulk export of teachers**: only students have an export endpoint. Trivial copy when needed.
- **Aadhaar full storage**: still last-4 only. Full encrypted Aadhaar lands in a v2 with proper key management.
- **Phone uniqueness scope**: globally unique for now (carried over from Module 1).

## Commands

```bash
# Backend
uv run ruff check .        # all clean
uv run pytest --tb=no -q   # 64 passing
uv run python manage.py seed_demo

# Stack
docker compose up          # postgres + redis + Django (auto-migrate + auto-seed)

# Frontend (separate terminal)
cd ~/git/skooly-stride && bun run dev
```
