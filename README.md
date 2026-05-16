# Skooly Backend

Django + Django Ninja + Postgres backend for the Skooly school management platform.

The frontend lives at `~/git/skooly-stride`. See `CLAUDE.md` for the build conventions and `docs/progress.md` for current status.

## Setup

```bash
# 1. Install uv if you don't have it (https://docs.astral.sh/uv/)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Bring up Postgres + Redis
docker compose up -d

# 3. Configure env
cp .env.example .env

# 4. Install Python deps + migrate
uv sync
uv run python manage.py migrate
uv run python manage.py createsuperuser   # optional, for /admin

# 5. Run
uv run python manage.py runserver
```

API docs: <http://localhost:8000/api/v1/docs>

## Development

```bash
uv run ruff check .        # lint
uv run ruff check . --fix  # auto-fix
uv run pytest --cov=apps   # tests + coverage
uv run python manage.py makemigrations
```

## Project layout

- `config/` — Django settings (split into base/dev/prod/test), URL routing, Ninja API root, Celery app.
- `apps/core/` — Tenant infrastructure (manager, contextvars, middleware, RLS helpers), shared schemas, exceptions, pagination.
- `apps/accounts/` — Custom User model, JWT auth dependency, all auth endpoints.
- `apps/schools/` — School and AcademicYear models + endpoints.
- `docs/` — Generated OpenAPI spec and module progress.
