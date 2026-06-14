"""Base Django settings — shared across all environments."""

from datetime import timedelta
from pathlib import Path

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config("SECRET_KEY", default="dev-insecure-change-me")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "corsheaders",
    "ninja_jwt",
    "django_celery_beat",
    "django_celery_results",
    # Local
    "apps.core",
    "apps.accounts",
    "apps.schools",
    "apps.people",
    "apps.academics",
    "apps.attendance",
    "apps.exams",
    "apps.fees",
    "apps.communications",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Serves collected static files (admin, /api/v1/docs assets) directly from
    # the app process — no separate static server needed. No-op in dev.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.TenantMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="skooly_dev"),
        "USER": config("DB_USER", default="skooly"),
        "PASSWORD": config("DB_PASSWORD", default="skooly"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
    }
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

LANGUAGE_CODE = "en-in"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

DISPLAY_TIME_ZONE = "Asia/Kolkata"

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# JWT
NINJA_JWT = {
    # Default of 11 520 min = 8 days so the teacher mobile app stays logged in
    # across the weekend without requiring a password re-entry.  The teacher's
    # app calls POST /auth/refresh on every foreground-resume to extend the
    # window proactively; the 5-day-inactivity logout lives in the frontend.
    # Override with JWT_ACCESS_TTL_MINUTES in .env for tighter security in prod.
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=config("JWT_ACCESS_TTL_MINUTES", default=11520, cast=int)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=config("JWT_REFRESH_TTL_DAYS", default=10, cast=int)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "SIGNING_KEY": config("JWT_SECRET", default=SECRET_KEY),
    "ALGORITHM": "HS256",
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "TOKEN_TYPE_CLAIM": "token_type",
}

# CORS
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:5173,http://localhost:3000",
    cast=Csv(),
)
CORS_ALLOW_CREDENTIALS = True

# Celery
CELERY_BROKER_URL = config("CELERY_BROKER_URL", default="redis://localhost:6379/1")
CELERY_RESULT_BACKEND = "django-db"
CELERY_CACHE_BACKEND = "django-cache"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ALWAYS_EAGER = config("CELERY_TASK_ALWAYS_EAGER", default=False, cast=bool)

# Redis cache
# Cache backend is env-driven. Prod can run without Redis by setting
# CACHE_BACKEND to LocMem (in-process). Nothing in the app relies on a shared
# cache yet, so this is safe; flip back to Redis when one is justified.
CACHES = {
    "default": {
        "BACKEND": config("CACHE_BACKEND", default="django.core.cache.backends.redis.RedisCache"),
        "LOCATION": config("REDIS_URL", default="redis://localhost:6379/0"),
    }
}

# WhatsApp
WHATSAPP_PROVIDER = config("WHATSAPP_PROVIDER", default="mock")
GUPSHUP_API_KEY = config("GUPSHUP_API_KEY", default="")
GUPSHUP_SOURCE_NUMBER = config("GUPSHUP_SOURCE_NUMBER", default="")

# OTP / SMS
MSG91_AUTH_KEY = config("MSG91_AUTH_KEY", default="")

# Storage. Media → Cloudflare R2 (S3) when USE_R2, else local disk. Static
# files default to plain storage here (dev-safe); prod swaps in WhiteNoise's
# compressed + hashed storage (see prod.py).
USE_R2 = config("USE_R2", default=False, cast=bool)
_media_storage = (
    {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "access_key": config("R2_ACCESS_KEY"),
            "secret_key": config("R2_SECRET_KEY"),
            "bucket_name": config("R2_BUCKET"),
            "endpoint_url": config("R2_ENDPOINT"),
            "signature_version": "s3v4",
        },
    }
    if USE_R2
    else {"BACKEND": "django.core.files.storage.FileSystemStorage"}
)
STORAGES = {
    "default": _media_storage,
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Sentry
SENTRY_DSN = config("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
    )
