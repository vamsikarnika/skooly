# Skooly Backend Progress

## Current Status

- Backend initialized: 2026-05-17
- Last session: 2026-05-17
- Current state: Module 1 done, **Module 2-lite** done (models + read endpoints + seed). Full Module 2 (CRUD + Excel import) still pending.

## Modules

- [x] Module 1: Foundation (auth, school, academic year, tenant infra)
- [~] Module 2: People & Structure — **lite**: models + read-only list/detail endpoints + seed. CRUD + Excel bulk import not yet built.
- [ ] Module 3: Attendance
- [ ] Module 4: Tests & Scores
- [ ] Module 5: WhatsApp Integration
- [ ] Module 6: Report Cards
- [ ] Module 7: Fees
- [ ] Module 8: Analytics
- [ ] Module 9: Parent Web View
- [ ] Module 10: Polish

## API Endpoints Built (19 endpoints)

All emit/accept camelCase at the wire boundary.

### Auth (`/api/v1/auth/`)
- `POST /signup`, `POST /login`, `POST /refresh`, `POST /forgot-password`, `POST /verify-otp`, `POST /reset-password`
- `GET /me` (auth)

### Schools (`/api/v1/schools/`) — auth, admin for writes
- `GET /current`, `PATCH /current`
- `GET /academic-years`, `POST /academic-years`, `PATCH /academic-years/{id}`

### People (`/api/v1/`) — auth, read-only
- `GET /students` (paginated; filters: `classId`, `sectionId`, `status`, `q`, `page`, `pageSize`)
- `GET /students/{id}`
- `GET /teachers` (paginated; filters: `status`)
- `GET /teachers/{id}`

### Academics (`/api/v1/`) — auth, read-only
- `GET /classes` (with nested sections + student counts, filters: `academicYearId`)
- `GET /sections/{id}`
- `GET /subjects`

OpenAPI captured at [docs/openapi.json](openapi.json).

## Demo seed

Run `python manage.py seed_demo` (idempotent — won't double-seed; `--reset` to wipe and recreate).

**The seeded school**: "Vidya Bharati High School" (Vijayawada, AP State Board).

| | Count |
|---|---|
| Students | ~660 (across all classes) |
| Teachers | 18 |
| Subjects | 9 (Telugu, Hindi, English, Math, Science variants, Social, CS) |
| Classes | 10 (Class 1–10) |
| Sections | 24 (2–3 sections per class) |
| Class teachers | Every section has one |
| Subject assignments | Each (section, subject) has a teacher |

**Admin login**: `+919876543210` / `demo1234`

Realistic Telugu/Indian names, AP cities for addresses, parent contacts with WhatsApp flags, age-appropriate DOBs by class level. Deterministic (uses `--seed=42`).

## Frontend wiring

- `src/lib/api/` — fetch client (auto bearer + one-shot 401 refresh), auth, students, classes API modules.
- `src/routes/admin/students/` — list and detail pages wired to real API via TanStack Query (pagination, class/section/status filters, search).
- `.env.development` defaults to `VITE_USE_MOCK_API=false`. Set `=true` in `.env.local` to fall back to MSW (auth-only handlers; Module 2+ endpoints not mocked).

## How to run the full demo

```bash
# 1. Bring up everything in one shot
cd ~/git/skooly
docker compose up                     # postgres + redis + Django (auto-migrate + auto-seed)

# 2. Start frontend (separate terminal)
cd ~/git/skooly-stride
bun install                            # first time only
bun run dev                            # opens http://localhost:8080

# 3. Sign in
# phone: +919876543210
# password: demo1234
```

To skip the seed on container start, set `SKOOLY_SEED_DEMO=false` in the api service env.

## Open questions

- **User phone uniqueness scope.** Made globally unique for v1 because `USERNAME_FIELD` must be. Same teacher at multiple schools → multiple phones for now.
- **Module 2-lite scope.** Skipped: full student/teacher CRUD, Excel bulk import, photo upload, transfer/promotion flows. These come with proper Module 2.
- **Frontend mock parity.** MSW handlers only cover auth + school endpoints. If you want offline mode for the new student/class/teacher pages, would need to extend `src/mocks/handlers/`.
- **RLS in tests.** Test runner uses SQLite (no Docker required). RLS is Postgres-only and disabled in tests; cross-tenant isolation is covered at the manager+middleware+HTTP level in the test suite.

## Test status

```bash
uv run ruff check .        # all checks pass
uv run pytest --cov=apps   # 27 tests pass, ~88% coverage on Module 1 code
```

Module 2-lite endpoints don't yet have a dedicated test file — covered by manual smoke-test against the seeded DB. Will add when full Module 2 lands.

## Frontend sync status

- Last sync: 2026-05-17
- Frontend repo HEAD: (uncommitted)
- Real-API pages: `/login`, `/signup`, `/admin/students`, `/admin/students/:id`.
- Mock-only pages (still using `lib/*-data.ts`): attendance, tests, fees, classes detail, teachers, announcements, analytics, report cards. These will be migrated as the corresponding backend modules land.
