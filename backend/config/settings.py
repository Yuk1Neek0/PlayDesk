"""
Django settings for PlayDesk.

Reads configuration from environment variables via django-environ.
Set DATABASE_URL (and other vars) in .env or the environment.
"""

from pathlib import Path

import environ

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# environ
# ---------------------------------------------------------------------------
env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["*"]),
    SECRET_KEY=(str, "django-insecure-change-me-in-production"),
)

# Read .env file if it exists (dev convenience; prod uses real env vars)
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    # Local
    "core",
    "api",
    "rag",
    "agent",
    "campaigns",
    "outbound",
    "pricing",
    "billing",
]

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.CurrentStoreMiddleware",
    "core.middleware.CustomerSessionMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://playdesk:playdesk@db:5432/playdesk",
    )
}

# Ensure psycopg v3 engine is used
DATABASES["default"].setdefault("ENGINE", "django.db.backends.postgresql")

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# ---------------------------------------------------------------------------
# Default primary key
# ---------------------------------------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
}

# ---------------------------------------------------------------------------
# LLM / embeddings (provider clients are injectable; tests mock them)
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
ANTHROPIC_MODEL = env("ANTHROPIC_MODEL", default="claude-opus-4-7")
OPENAI_API_KEY = env("OPENAI_API_KEY", default="")
EMBEDDING_MODEL = env("EMBEDDING_MODEL", default="text-embedding-3-small")
EMBEDDING_DIMENSIONS = env.int("EMBEDDING_DIMENSIONS", default=1536)

# Agent loop
AGENT_MAX_ITERATIONS = env.int("AGENT_MAX_ITERATIONS", default=6)
RAG_TOP_K = env.int("RAG_TOP_K", default=5)

# ---------------------------------------------------------------------------
# Stripe — test-mode booking deposits (enhancements epic)
# ---------------------------------------------------------------------------
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_PUBLISHABLE_KEY = env("STRIPE_PUBLISHABLE_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")
STRIPE_TEST_MODE = env.bool("STRIPE_TEST_MODE", default=True)
STRIPE_SUCCESS_URL = env("STRIPE_SUCCESS_URL", default="http://localhost:3000/?payment=success")
STRIPE_CANCEL_URL = env("STRIPE_CANCEL_URL", default="http://localhost:3000/?payment=cancelled")
# How long an unpaid pending_payment hold survives before expire_holds reaps it.
STRIPE_HOLD_MINUTES = env.int("STRIPE_HOLD_MINUTES", default=10)
# Public URL of the admin frontend — onboarding return links and Checkout
# success URLs are built from this. Defaults to the dev server.
SITE_URL = env("SITE_URL", default="http://localhost:3000")

# Email backend defaults to console in dev so receipt emails log instead
# of erroring out without SMTP. Tests override to locmem via pytest-django.
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@playdesk.local")

# ---------------------------------------------------------------------------
# Sessions — v10a staff-auth ships real Django session login for /admin/*.
# Settings are explicit (not Django defaults) so the cookie security stance
# is reviewable in one place. SESSION_COOKIE_SECURE flips to True in prod
# via the env var; dev/test runs over plain HTTP and must allow the cookie.
# ---------------------------------------------------------------------------
SESSION_COOKIE_AGE = 14 * 24 * 3600  # 14 days
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=False)
LOGIN_URL = "/staff/login/"

# ---------------------------------------------------------------------------
# Caches — Django LocMem cache backs the customer-portal OTP rate-limiter.
# Production should swap this for Redis once the workload justifies it.
# ---------------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "playdesk-default",
    },
}

# ---------------------------------------------------------------------------
# Twilio — SMS channel (multi-channel epic)
# ---------------------------------------------------------------------------
TWILIO_ACCOUNT_SID = env("TWILIO_ACCOUNT_SID", default="")
TWILIO_AUTH_TOKEN = env("TWILIO_AUTH_TOKEN", default="")
