"""Test settings — used by pytest."""

from .base import *

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

SECRET_KEY = "test-secret-key-with-enough-bytes-for-hs256-jwt-signing"
NINJA_JWT["SIGNING_KEY"] = SECRET_KEY

# Faster password hasher for tests.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Run Celery tasks synchronously in tests.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Disable RLS in tests — the TenantManager + middleware are what we test.
# RLS is a defence-in-depth layer that requires a Postgres role separate from
# the migration role, which adds noise to the test setup.
TENANT_USE_POSTGRES_RLS = False

# Tests use SQLite — fast, self-contained, no Docker required.
# RLS is a Postgres-only defence-in-depth layer, disabled in tests anyway.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Disable real cache during tests.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}
