# Skooly Backend — Claude Code Build Prompt

> **How to use this document:** Save this file at the root of your new backend repo as `CLAUDE.md`. Claude Code will read it automatically as project context on every session. Then start with the prompts in the "Session 1" section at the end.

---

## Project Context

You are building **Skooly**, a school management platform for Indian schools (starting with Andhra Pradesh State Board). The frontend already exists at `~/git/skooly-stride` (React + TypeScript + Vite + TailwindCSS + shadcn/ui). You are building the **backend API** that the frontend will consume.

**Critical rule:** The frontend is the contract. Every API endpoint you build must match exactly what the frontend already calls — URL paths, HTTP methods, request payload shapes, response shapes, status codes. Do not invent new endpoints or shapes without first inspecting the frontend code.

**Repo structure:**
- Frontend repo: `~/git/skooly-stride` (separate repo, READ-ONLY from your perspective — you inspect it but never modify it)
- Backend repo: the current directory (where you create everything)

---

## Tech Stack (Locked)

- **Language:** Python 3.12+
- **Framework:** Django 5.x
- **API layer:** Django Ninja (NOT DRF)
- **Validation:** Pydantic v2 (via Django Ninja)
- **Database:** PostgreSQL 16+
- **ORM:** Django ORM
- **Driver:** `psycopg[binary]`
- **Background jobs:** Celery 5.x + Redis
- **Cache:** Redis
- **JWT auth:** `django-ninja-jwt`
- **File storage:** `django-storages` with Cloudflare R2 (S3-compatible) — use local storage in dev
- **PDF generation:** WeasyPrint (Python-native, HTML/CSS to PDF)
- **Excel:** `openpyxl`
- **HTTP client:** `httpx` (for outbound WhatsApp BSP calls)
- **Password hashing:** Argon2 (Django default acceptable)
- **Dependency management:** `uv`
- **Linting/formatting:** `ruff`
- **Type checking:** `mypy` with `django-stubs`
- **Testing:** `pytest` + `pytest-django` + `factory_boy`
- **Process management:** Gunicorn + Nginx (prod), `manage.py runserver` (dev)

**Do NOT introduce:** DRF, FastAPI, SQLAlchemy, MongoDB, Pipenv, Poetry, Black, Flake8, isort (`ruff` replaces all of these).

---

## Mandatory First Step Every Session

**Before writing or modifying any backend code, you must:**

1. **Read the frontend code** at `~/git/skooly-stride` to understand what API calls the frontend makes.
2. **Specifically inspect:**
   - `src/lib/api/` or `src/services/` or `src/api/` (wherever HTTP calls live)
   - `src/types/` (TypeScript types representing API request/response shapes)
   - `src/hooks/` (data-fetching hooks, often `useQuery`/`useMutation` with URLs)
   - Any axios/fetch wrapper or API client file
   - `.env`, `.env.example`, `vite.config.ts` for `VITE_API_BASE_URL` or similar
3. **List every API endpoint** the frontend calls: method, URL path, request payload type, response type, query parameters, auth requirements.
4. **Then build backend endpoints that exactly match.**

If the frontend has not yet implemented a feature mentioned in this document, build the backend for it anyway following the conventions below. When the frontend catches up, the contract will already exist.

If you find a frontend API call that's ambiguous (e.g., the response type is `any`), **ask before guessing**. Do not invent shapes that the frontend doesn't already expect.

---

## API Conventions (Match Frontend Exactly)

These are defaults. If the frontend uses different conventions, **match the frontend**.

### URL Structure

- Base: `/api/v1/`
- Resource paths: `/api/v1/{resource}/`, `/api/v1/{resource}/{id}/`
- Sub-resources: `/api/v1/{resource}/{id}/{sub-resource}/`
- Trailing slashes: include them (Django convention)

### HTTP Methods

- `GET` for reads
- `POST` for creates and actions
- `PATCH` for partial updates (preferred over PUT)
- `DELETE` for deletes (soft-delete in DB)

### Response Shapes

For single resource:
```json
{ "id": 1, "field": "value", ... }
```

For list endpoints (paginated):
```json
{
  "items": [...],
  "count": 150,
  "page": 1,
  "page_size": 50,
  "total_pages": 3
}
```

For errors:
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable message",
    "details": { "field_name": ["specific error"] }
  }
}
```

For action endpoints (e.g., publish, send reminders):
```json
{ "success": true, "message": "...", "data": { ... } }
```

**If the frontend expects different shapes, override these defaults and match the frontend.**

### Pagination

- Query params: `?page=N&page_size=M`
- Default page_size: 50
- Max page_size: 200

### Filtering

- Query params with snake_case: `?section_id=1&status=active&from_date=2026-01-01`

### Authentication

- JWT in `Authorization: Bearer <token>` header
- Tokens contain: `user_id`, `school_id`, `role`, `exp`
- Access token: 15 min expiry
- Refresh token: 7 days expiry, rotated on each refresh

### Dates and Times

- All date/time in API responses: ISO 8601 (`2026-05-17T10:30:00+05:30`)
- Date-only fields: `2026-05-17`
- All datetimes stored as UTC in DB, displayed in IST (`Asia/Kolkata`) in API responses

### Money

- Always integer paise in DB
- API responses: send as integer paise, frontend handles display
- E.g., ₹4,500.00 is `450000` paise

---

## Multi-Tenancy (Critical — Get This Right)

Every table except `schools`, `users` (during signup), and global config must have `school_id`.

### Three-Layer Enforcement

**Layer 1: Base model + custom manager**

```python
# apps/core/models.py
from django.db import models
from apps.core.context import get_current_school

class TenantManager(models.Manager):
    def get_queryset(self):
        qs = super().get_queryset().filter(deleted_at__isnull=True)
        school = get_current_school()
        if school is None:
            return qs.none()  # fail closed
        return qs.filter(school=school)
    
    def all_tenants(self):
        """Bypass tenant filter. Use only for admin scripts and Celery system jobs."""
        return super().get_queryset()

class TenantScopedModel(models.Model):
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    
    objects = TenantManager()
    
    class Meta:
        abstract = True
```

**Layer 2: Middleware sets school context from JWT**

Use `contextvars` (not threadlocals) for async safety. Middleware extracts `school_id` from authenticated JWT and sets it on a contextvar that the manager reads.

**Layer 3: Postgres Row-Level Security**

For every tenant table, enable RLS and add a policy:
```sql
ALTER TABLE students ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON students
    USING (school_id = current_setting('app.current_school_id', true)::int);
```

Middleware also sets `app.current_school_id` per database connection using `SET LOCAL`.

**Test cross-tenant isolation explicitly.** Every module needs at least one test that confirms a user from School A cannot access School B's data, even with crafted requests.

---

## Project Structure

```
skooly-api/
├── pyproject.toml
├── uv.lock
├── manage.py
├── .env.example
├── .gitignore
├── ruff.toml
├── mypy.ini
├── pytest.ini
├── pre-commit-config.yaml
├── docker-compose.yml          # local Postgres + Redis
├── CLAUDE.md                   # this file
├── README.md
├── config/
│   ├── __init__.py
│   ├── settings/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── dev.py
│   │   ├── prod.py
│   │   └── test.py
│   ├── urls.py
│   ├── api.py                  # Django Ninja root API
│   ├── celery.py
│   ├── wsgi.py
│   └── asgi.py
├── apps/
│   ├── core/
│   │   ├── models.py           # TenantScopedModel, TenantManager
│   │   ├── context.py          # contextvars for school
│   │   ├── middleware.py       # TenantMiddleware
│   │   ├── permissions.py      # require_role, require_school_match
│   │   ├── pagination.py
│   │   ├── exceptions.py       # custom exceptions, exception handlers
│   │   ├── audit.py            # audit logging
│   │   └── utils.py
│   ├── accounts/               # User, JWT auth
│   ├── schools/                # School, AcademicYear
│   ├── people/                 # Student, Teacher
│   ├── academics/              # Class, Section, Subject, Enrollment
│   ├── attendance/
│   ├── exams/                  # Test, Score, ReportCard
│   ├── fees/                   # FeeStructure, StudentFee, Payment
│   ├── communications/         # WhatsApp, Announcements
│   └── analytics/
├── tests/                      # cross-app integration tests
├── deployment/
│   ├── nginx.conf
│   ├── gunicorn.conf.py
│   ├── systemd/
│   └── scripts/
└── docs/
```

**Convention per Django app:**

```
apps/<app_name>/
├── __init__.py
├── apps.py
├── models.py
├── managers.py           # if custom managers needed beyond TenantManager
├── schemas.py            # Pydantic schemas for API (in/out)
├── api.py                # Django Ninja router
├── services.py           # Business logic — THE important file
├── selectors.py          # Read queries (optional)
├── tasks.py              # Celery tasks
├── permissions.py        # Permission helpers
├── admin.py              # Django admin
├── signals.py            # Django signals (audit log triggers)
├── tests/
│   ├── __init__.py
│   ├── factories.py
│   ├── test_models.py
│   ├── test_services.py
│   ├── test_api.py
│   └── test_tenant_isolation.py
└── migrations/
```

**Architectural rule:** API handlers are thin. All business logic lives in `services.py`. API handlers parse input via Pydantic schemas, call services, return responses. Never write business logic in `api.py`.

---

## Data Model Reference

This is the canonical schema. Adjust field types and add fields based on what the frontend actually needs. Always cross-check with frontend types before finalizing.

### Module 1 — Foundation

**`accounts.User`** (custom user model, `AUTH_USER_MODEL`)
- id (PK)
- school (FK to schools.School)
- phone (string, unique within school)
- email (string, nullable, unique within school)
- password (Django default hashed)
- first_name, last_name
- role (enum: `admin`, `teacher`)
- is_active (bool)
- last_login_at, created_at, updated_at

**`schools.School`**
- id
- name
- board (enum: `AP_STATE`, `CBSE`, `ICSE`, `OTHER`)
- address (text)
- logo_url (string)
- whatsapp_number (string)
- whatsapp_bsp_config (JSONField)
- primary_color (string)
- current_academic_year (FK, nullable)
- created_at, updated_at

**`schools.AcademicYear`**
- id, school (FK)
- label (e.g., "2025-26")
- start_date, end_date
- is_current (bool)

### Module 2 — People & Structure

**`people.Student`** (TenantScoped)
- admission_number (unique per school)
- first_name, last_name
- dob, gender
- aadhaar (encrypted at rest, optional)
- photo_url
- blood_group
- address
- parent1_name, parent1_phone, parent1_relation
- parent2_name, parent2_phone, parent2_relation
- primary_whatsapp_phone
- emergency_contact_name, emergency_contact_phone
- previous_school
- admission_date, withdrawal_date
- status (enum: `active`, `withdrawn`, `graduated`)

**`people.Teacher`** (TenantScoped)
- user (OneToOne to accounts.User)
- first_name, last_name
- phone, email
- qualification (text)
- joining_date
- status (enum: `active`, `inactive`)

**`academics.Subject`** (TenantScoped)
- name, code

**`academics.Class`** (TenantScoped)
- academic_year (FK)
- name (e.g., "Class 8")
- display_order (int)

**`academics.Section`** (TenantScoped)
- class_obj (FK, field name `class_` not allowed)
- name (A/B/C)
- class_teacher (FK to Teacher, nullable)
- room_number
- capacity (int)

**`academics.StudentEnrollment`** (TenantScoped)
- student (FK), section (FK), academic_year (FK)
- enrollment_date
- status (enum: `active`, `transferred`, `withdrawn`)

**`academics.TeacherAssignment`** (TenantScoped)
- teacher (FK), subject (FK), section (FK), academic_year (FK)

**`academics.SubjectClassMapping`** (TenantScoped)
- subject (FK), class_obj (FK)

### Module 3 — Attendance

**`attendance.Attendance`** (TenantScoped)
- student (FK), section (FK)
- date
- status (enum: `present`, `absent`, `late`, `half_day`)
- marked_by (FK to Teacher)
- marked_at
- notes
- Unique: (student, date)
- Indexes: (school, date), (student, date)

### Module 4 — Tests & Scores

**`exams.Test`** (TenantScoped)
- section (FK), subject (FK)
- name
- test_type (enum: `FA1`, `FA2`, `FA3`, `FA4`, `SA1`, `SA2`, `OTHER`)
- test_date
- max_marks (int)
- created_by (FK to Teacher)
- published_at (datetime, nullable — null = draft)

**`exams.TestScore`** (TenantScoped)
- test (FK), student (FK)
- marks_obtained (decimal, nullable if absent)
- is_absent (bool)
- entered_by (FK to Teacher)
- entered_at
- Unique: (test, student)

### Module 5 — Communications

**`communications.WhatsAppTemplate`** (TenantScoped)
- template_key (enum, e.g., `attendance_absent`)
- meta_template_name
- meta_template_status (enum: `PENDING`, `APPROVED`, `REJECTED`)
- template_body
- variables (JSONField — list of variable names)

**`communications.WhatsAppMessage`** (TenantScoped)
- student (FK, nullable)
- parent_phone
- template_key
- payload (JSONField)
- bsp_message_id (string, nullable)
- status (enum: `queued`, `sent`, `delivered`, `read`, `failed`)
- error_message
- sent_at, delivered_at

**`communications.Announcement`** (TenantScoped)
- title, body
- target_type (enum: `all`, `class`, `section`, `individual`)
- target_ids (JSONField — list of IDs)
- created_by (FK to User)
- sent_at

### Module 6 — Report Cards

**`exams.ReportCard`** (TenantScoped)
- student (FK)
- academic_year (FK)
- term (enum: `term1`, `term2`, `annual`)
- generated_at
- published_at (nullable)
- pdf_url
- data_snapshot (JSONField — frozen at generation time)

### Module 7 — Fees

**`fees.FeeStructure`** (TenantScoped)
- academic_year (FK), class_obj (FK)
- name

**`fees.FeeComponent`** (TenantScoped)
- fee_structure (FK)
- name (e.g., "Tuition", "Transport")
- amount (integer paise)
- due_date
- is_optional (bool)
- display_order

**`fees.StudentFee`** (TenantScoped)
- student (FK), fee_structure (FK), academic_year (FK)
- total_amount, discount_amount, discount_reason
- final_amount, paid_amount
- status (enum: `pending`, `partial`, `paid`, `overdue`)

**`fees.StudentFeeComponent`** (TenantScoped)
- student_fee (FK), fee_component (FK)
- applied_amount, is_applicable

**`fees.FeePayment`** (TenantScoped)
- student_fee (FK)
- amount (paise)
- payment_mode (enum: `cash`, `cheque`, `online`, `bank_transfer`)
- reference_number
- paid_on (date)
- received_by (FK to User)
- receipt_number (auto-generated, unique per school)
- notes
- receipt_pdf_url

### Module 10 — Core/Polish

**`core.AuditLog`** (TenantScoped)
- user (FK, nullable for system actions)
- action (string)
- model_name, object_id
- changes (JSONField)
- ip_address
- timestamp

---

## Build Sequence (Module by Module)

Build modules **in this order**. Each module must be fully working (with tests passing, including tenant isolation tests) before moving to the next.

### Module 1: Foundation
- Custom User model (BEFORE first migration)
- School, AcademicYear models
- JWT auth endpoints
- Tenant middleware + base model
- Postgres RLS migration helpers
- Role-based access decorator
- Django admin for these models

### Module 2: People & Structure
- All people and academics models
- CRUD APIs for students, teachers, subjects, classes, sections
- Bulk import via Excel (Celery task)
- Excel export
- File upload for student photos (R2 in prod, local in dev)

### Module 3: Attendance
- Attendance model + APIs
- Edit window enforcement
- WhatsApp queue trigger on absent (batched per save)

### Module 4: Tests & Scores
- Test + TestScore models + APIs
- Bulk score entry endpoint (paste-from-Excel support)
- Publish action triggering WhatsApp dispatch

### Module 5: WhatsApp Integration
- Provider abstraction interface
- Mock provider (dev) + Gupshup provider (prod-ready)
- Celery task for dispatch with retries
- BSP webhook receiver for delivery status
- Template registry seed

### Module 6: Report Cards
- ReportCard model + generation service
- WeasyPrint HTML template for AP Board format
- Bulk generation as Celery task
- Publish action (WhatsApp dispatch)

### Module 7: Fees
- All fees models + APIs
- Apply structure to class with overrides
- Payment recording with auto-generated receipt PDF
- Dues report with filtering
- Bulk reminders endpoint
- Money handling: integer paise everywhere

### Module 8: Analytics
- Dashboard endpoints with Redis caching
- Section, student, school-level metrics
- "Needs attention" computation — frame language carefully (NEVER label students "weak")

### Module 9: Parent Web View
- Tokenized link auth (no login)
- Read-only endpoints scoped to single student
- Token expiry handling

### Module 10: Polish
- Audit log + signals
- Excel exports for all major lists
- Health check endpoints
- Backup scripts
- Final security review

---

## Frontend Integration Workflow

For every module, follow this loop:

1. **Inspect frontend code** at `~/git/skooly-stride` for this module's API calls.
2. **Document the contracts** you find: list every endpoint with method, URL, request schema, response schema. Show this list to the user before building.
3. **Build Pydantic schemas** in `apps/<module>/schemas.py` that exactly match the frontend's TypeScript types.
4. **Build Django models** to back the data.
5. **Build service functions** in `services.py` with business logic.
6. **Build Django Ninja routers** in `api.py` that match the frontend's expected URLs/methods/shapes.
7. **Write tests** including cross-tenant isolation tests.
8. **Generate OpenAPI schema** and confirm Django Ninja's output matches frontend expectations.
9. **Provide the user with curl examples** for each endpoint so they can test independently.

If a frontend type uses a field name like `firstName` (camelCase), Django Ninja must serialize it that way (configure Pydantic with `alias_generator`). If frontend uses `first_name` (snake_case), match that. **Frontend's naming wins.**

---

## Authentication Architecture

### Signup Flow (school admin creating new school)
```
POST /api/v1/auth/signup
{
  "school_name": "...",
  "board": "AP_STATE",
  "address": "...",
  "academic_year_label": "2025-26",
  "academic_year_start": "2025-06-01",
  "academic_year_end": "2026-04-30",
  "admin_first_name": "...",
  "admin_last_name": "...",
  "admin_phone": "+919876543210",
  "admin_email": "admin@school.com",
  "admin_password": "..."
}
→ Returns { user, school, access_token, refresh_token }
```

### Login
```
POST /api/v1/auth/login
{ "phone": "+919876543210", "password": "..." }
→ Returns { user, school, access_token, refresh_token }
```

### Token Refresh
```
POST /api/v1/auth/refresh
{ "refresh_token": "..." }
→ Returns { access_token, refresh_token } (refresh rotated)
```

### Forgot Password (OTP via WhatsApp/SMS)
```
POST /api/v1/auth/forgot-password { "phone": "..." }
POST /api/v1/auth/verify-otp { "phone": "...", "otp": "123456" } → returns reset_token
POST /api/v1/auth/reset-password { "reset_token": "...", "new_password": "..." }
```

### Current User
```
GET /api/v1/auth/me
→ Returns { user, school, permissions }
```

### Parent Token-Based Auth (No Login)
For parent web views:
- WhatsApp messages include URLs like `https://app.skooly.in/p/{token}`
- Token is signed JWT with `{ student_id, exp }`
- Backend validates token in `/api/v1/parent/...` endpoints
- Read-only access scoped to single student

**Match the frontend's exact auth flow.** If frontend stores tokens in localStorage, body, or cookies — match whichever it uses.

---

## WhatsApp Provider Architecture

Build abstraction layer in `apps/communications/providers/`:

```python
# base.py
class WhatsAppProvider(ABC):
    @abstractmethod
    def send_template(self, phone: str, template: str, variables: dict) -> BSPResponse: ...
    @abstractmethod
    def get_status(self, message_id: str) -> str: ...

# mock.py — for dev (logs to console + DB, returns fake message IDs)
# gupshup.py — Gupshup API
# aisensy.py — AiSensy API
```

Factory:
```python
def get_whatsapp_provider(school: School) -> WhatsAppProvider:
    if settings.WHATSAPP_PROVIDER == "mock":
        return MockProvider()
    config = school.whatsapp_bsp_config
    if config["provider"] == "gupshup":
        return GupshupProvider(api_key=config["api_key"], source_number=school.whatsapp_number)
    ...
```

Celery task with retries:
```python
@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def send_whatsapp_message(self, message_id: int):
    msg = WhatsAppMessage.objects.all_tenants().get(id=message_id)
    if msg.status in ("sent", "delivered", "read", "failed"):
        return  # idempotent
    try:
        provider = get_whatsapp_provider(msg.school)
        response = provider.send_template(msg.parent_phone, msg.template_key, msg.payload)
        msg.bsp_message_id = response.message_id
        msg.status = "sent"
        msg.sent_at = timezone.now()
        msg.save()
    except BSPRetryableError as e:
        raise self.retry(exc=e)
    except BSPPermanentError as e:
        msg.status = "failed"
        msg.error_message = str(e)
        msg.save()
```

Webhook receiver for delivery status:
```
POST /api/v1/webhooks/whatsapp/{school_id}/
```

---

## Code Quality Rules

- **Type hints everywhere.** Use `mypy --strict` mode.
- **Pydantic schemas for every API input/output.** Never expose raw model serialization to API.
- **No business logic in API handlers.** Handlers parse → call service → return.
- **Idempotent Celery tasks.** Always check current state before acting.
- **No raw SQL with user input.** Use ORM. Raw SQL only for read-only analytics queries with no user input.
- **Money: always integer paise.** Never use floats for currency. Display formatting is frontend's job.
- **Timezones: store UTC, return ISO 8601 with offset.** Use `timezone.now()`, never `datetime.now()`.
- **Soft delete by default.** Set `deleted_at`, don't actually delete.
- **Audit log critical writes:** mark/edit scores, edit fees, record payment, edit student data, bulk operations.
- **Tenant isolation tests for every module.** Cross-tenant access attempts must fail with 404 (not 403 — don't leak existence).

---

## Testing Requirements

Every module must include:

1. **Unit tests** for service functions (mock external calls).
2. **API tests** for every endpoint (success + error paths).
3. **Tenant isolation test** — user from School A trying to access School B's data returns 404.
4. **Permission tests** — teachers can't access admin-only endpoints, etc.

Use `factory_boy` for fixtures, `pytest-django` as the runner. Aim for 70%+ coverage on services.

Run before declaring a module done:
```bash
uv run ruff check .
uv run mypy .
uv run pytest --cov=apps --cov-fail-under=70
```

---

## Environment & Configuration

### Environment Variables

Provide `.env.example`:

```env
# Django
DJANGO_SETTINGS_MODULE=config.settings.dev
SECRET_KEY=changeme
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database
DATABASE_URL=postgresql://skooly:skooly@localhost:5432/skooly_dev

# Redis
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1

# JWT
JWT_SECRET=changeme
JWT_ACCESS_TTL_MINUTES=15
JWT_REFRESH_TTL_DAYS=7

# WhatsApp
WHATSAPP_PROVIDER=mock  # mock | gupshup | aisensy
GUPSHUP_API_KEY=
GUPSHUP_SOURCE_NUMBER=

# OTP / SMS
MSG91_AUTH_KEY=

# File Storage
USE_R2=False  # local in dev, R2 in prod
R2_ACCESS_KEY=
R2_SECRET_KEY=
R2_BUCKET=skooly-files
R2_ENDPOINT=

# CORS
CORS_ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000

# Sentry
SENTRY_DSN=
```

### CORS

Frontend dev runs on `http://localhost:5173` (Vite default) or similar. Configure `django-cors-headers` to allow it.

### Docker Compose (local dev)

`docker-compose.yml` should run Postgres 16 and Redis 7. Django runs on host (not in container) for faster iteration.

---

## What NOT to Build in v1

To stay focused:

- ❌ Payment gateway integration (manual recording only)
- ❌ AI features (question generation, MCQ scoring)
- ❌ Native parent or teacher apps (web only)
- ❌ Two-way parent communication (WhatsApp is outbound only)
- ❌ Timetable, homework, library, transport, hostel modules
- ❌ Offline support (online required)
- ❌ Multi-language UI (English only)
- ❌ Real-time features (no WebSockets needed)

Design data model and abstractions so these can be added later without rewrites — but don't build them now.

---

## Critical Risks to Watch

1. **Tenant isolation bugs.** One school's data leaking to another is an extinction-level event for trust. Test cross-tenant access on every endpoint.
2. **Excel bulk import edge cases.** Schools will upload garbage. Validate every row, surface specific errors per row, never partial-import without confirmation.
3. **Money calculation errors.** Use integer paise, never floats. Test fee calculations with discounts, sibling overrides, partial payments.
4. **Report card format mismatch.** If output doesn't match what the school uses, they reject the tool. Build configurable templates.
5. **WhatsApp template rejections.** Submit Meta template applications early. Plan for 1-3 day approval delay.
6. **Frontend-backend contract drift.** This is why you read frontend first every session. Never invent shapes.

---

## Session Workflow

### Detecting session state at the start of any session

This file is read on **every** session. Do NOT assume it's the first session. Always check current state before acting.

At the start of any session, before doing anything else:

1. Check if the backend has been initialized:
   - Is there a `manage.py` in the current directory?
   - Is there a `pyproject.toml` with Django dependencies?
   - Is there a `docs/progress.md`?

2. **If none of those exist**, you are in Session 1 (first session ever for this project). Follow the "First-time setup" flow below.

3. **If they exist**, the project is already initialized. Follow the "Resuming work" flow below.

4. Either way, **wait for the user's instruction** before writing code. Don't auto-start building.

### First-time setup (only on Session 1, when repo is empty)

Do these steps only when the repo has not been initialized yet:

**Step 1: Verify the frontend repo exists.**

Check that `~/git/skooly-stride` exists and is a git repo. List its top-level structure to confirm it's a React/Vite project. If it doesn't exist, stop and ask the user where the frontend lives.

**Step 2: Inspect frontend for API patterns.**

Look for:
- API client setup (axios instance, fetch wrapper)
- Base URL configuration
- Auth token handling (how it's stored, attached to requests)
- Existing API call patterns (TanStack Query? Plain fetch? Redux?)
- Type definitions for API responses

Report findings to the user.

**Step 3: Confirm tech stack with the user.**

Show the user the stack from this document and confirm:
- Python + Django + Django Ninja (not DRF)
- Postgres
- Celery + Redis
- WeasyPrint for PDFs

Get explicit approval before proceeding.

**Step 4: Initialize the backend project.**

```bash
uv init --python 3.12
uv add django "django-ninja>=1.0" "psycopg[binary]" celery redis django-storages \
    django-cors-headers django-ninja-jwt argon2-cffi httpx weasyprint openpyxl \
    python-decouple django-celery-beat django-celery-results sentry-sdk Pillow
uv add --dev ruff mypy django-stubs pytest pytest-django factory-boy pytest-cov pre-commit

uv run django-admin startproject config .
```

Set up:
- Project structure as specified earlier in this document
- Settings split (base/dev/prod/test)
- `.env.example`
- `docker-compose.yml` for Postgres + Redis
- `ruff.toml`, `mypy.ini`, `pytest.ini`
- `.gitignore`
- `README.md` with setup instructions

**Step 5: Initialize progress tracking.**

Create `docs/progress.md`:

```markdown
# Skooly Backend Progress

## Current Status

Backend initialized: <date>
Last session: <date>
Current module: Module 1 (in progress)

## Modules

- [ ] Module 1: Foundation
- [ ] Module 2: People & Structure
- [ ] Module 3: Attendance
- [ ] Module 4: Tests & Scores
- [ ] Module 5: WhatsApp Integration
- [ ] Module 6: Report Cards
- [ ] Module 7: Fees
- [ ] Module 8: Analytics
- [ ] Module 9: Parent Web View
- [ ] Module 10: Polish

## API Endpoints Built

(filled in as you go)

## Open Questions

(filled in as you encounter ambiguity)

## Frontend Sync Status

Last frontend sync: <date>
Frontend repo HEAD: <sha>
```

**Step 6: Build Module 1 — Foundation.**

Order:
1. Create `apps/accounts` with custom User model — DO NOT MIGRATE YET until User model and `AUTH_USER_MODEL` setting are correct.
2. Create `apps/schools` with School and AcademicYear models.
3. Create `apps/core` with TenantScopedModel, TenantManager, context utils, middleware.
4. Configure `AUTH_USER_MODEL = "accounts.User"` in settings.
5. Set up Django Ninja root API at `/api/v1/` in `config/api.py`.
6. Build auth endpoints: signup, login, refresh, forgot-password, verify-otp, reset-password, me.
7. Build school settings endpoints: GET/PATCH `/api/v1/schools/current`.
8. Build academic year endpoints.
9. Write tests including tenant isolation tests.
10. Run lint, type-check, full test suite.
11. Generate OpenAPI schema, save to `docs/openapi.json`, show user the result.
12. Update `docs/progress.md` to mark Module 1 complete.

After Module 1 is complete and tests pass, **stop and ask the user before proceeding to Module 2.** Each module is a checkpoint.

### Resuming work (every session after Session 1)

When the repo is already initialized:

1. Read `docs/progress.md` to find the current state — which modules are done, which is in progress, any open questions.
2. Read frontend code at `~/git/skooly-stride` for any new or changed API calls since last session. Compare the frontend's current state against what's noted under "Frontend Sync Status" in `docs/progress.md`.
3. Skim recent backend code (especially any module marked "in progress") to refresh context.
4. **Briefly summarize to the user**: what's done, what's in progress, any frontend changes detected.
5. **Ask the user what to work on this session.** Do not assume — they may want to continue the next module, fix a bug, address an open question, or change direction.
6. Only after the user confirms, begin work.

### Working on a module

1. List all frontend API calls related to this module.
2. Show contracts (URL, method, request, response) to user for confirmation.
3. Build models → schemas → services → API routes → tests.
4. Run lint, type-check, tests.
5. Update `docs/progress.md` (mark module complete, list new endpoints, update sync status).
6. Show user how to test endpoints (curl examples).

### Ending a session

1. Commit work with descriptive message.
2. Update `docs/progress.md` with the current state.
3. Note any open questions or blockers.

---

## Style and Communication

- **Be direct.** Don't hedge or pad. State what you're building and why.
- **Ask before assuming.** If the frontend has ambiguous types or the user's request is unclear, ask.
- **Show your work.** When you discover frontend API calls, list them before building backend.
- **Don't over-engineer.** Build what's needed for the current module, no more.
- **Flag risks immediately.** Tenant isolation issues, money calculation concerns, anything that could lose data — surface them, don't bury them.

---

## Final Notes for the Builder

This is a real product going to real schools managing real students' data. Quality matters:
- A bug in attendance affects a parent's day.
- A bug in fees affects family finances.
- A bug in marks affects a student's record.
- A multi-tenancy bug could end the company.

Move fast, but verify. Read frontend code carefully. Test tenant isolation paranoidly. Use Postgres transactions for anything involving money. Log audit trails for sensitive changes.

This file (`CLAUDE.md`) is your persistent project memory. State that changes session-to-session (what's done, what's next) lives in `docs/progress.md`. At the start of every session, detect which state you're in (first-time setup vs resuming) and wait for the user's instruction before writing code.
