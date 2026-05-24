"""Dev settings — local development."""

from .base import *

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]

# Allow any localhost origin during dev (Vite default is 5173, but ports vary).
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^http://localhost:\d+$",
    r"^http://127\.0\.0\.1:\d+$",
]

# Skip RLS in dev to make running locally without superuser quirks easier.
# Tenant manager + middleware still enforce isolation.
TENANT_USE_POSTGRES_RLS = False

# Surface our app loggers' INFO to the console in dev (e.g. the mock OTP code,
# audit events). Prod keeps its own config; tests use test settings.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "apps": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
