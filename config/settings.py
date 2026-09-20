import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load local environment variables from .env if present
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in ("true", "1", "yes", "on")


SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-key-for-athar")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = [host.strip() for host in os.getenv("ALLOWED_HOSTS", "*").split(",") if host.strip()] or ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "core.middleware.HeaderSessionMiddleware",
]

ROOT_URLCONF = "config.urls"

# Template loaders: Django wraps the default loaders in cached.Loader, which
# means template edits are invisible until the server restarts. In DEBUG we use
# the plain loaders so `runserver` picks up template changes immediately.
TEMPLATE_LOADERS = [
    "django.template.loaders.filesystem.Loader",
    "django.template.loaders.app_directories.Loader",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": False,
        "OPTIONS": {
            "loaders": TEMPLATE_LOADERS if DEBUG else [
                ("django.template.loaders.cached.Loader", TEMPLATE_LOADERS),
            ],
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database configuration: Supabase (PostgreSQL) with SQLite local fallback
database_url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL")

if not database_url and os.getenv("SUPABASE_DB_HOST") and os.getenv("SUPABASE_DB_PASSWORD"):
    user = os.getenv("SUPABASE_DB_USER", "postgres")
    password = os.getenv("SUPABASE_DB_PASSWORD", "")
    host = os.getenv("SUPABASE_DB_HOST")
    port = os.getenv("SUPABASE_DB_PORT", "5432")
    name = os.getenv("SUPABASE_DB_NAME", "postgres")
    database_url = f"postgresql://{user}:{password}@{host}:{port}/{name}?sslmode=require"

use_supabase = False
if database_url:
    # Test if the external database host is directly reachable (handles network-isolated sandboxes)
    try:
        import psycopg
        test_conn = psycopg.connect(database_url, connect_timeout=1)
        test_conn.close()
        use_supabase = True
    except Exception:
        use_supabase = False

if use_supabase and database_url:
    is_pooler = "6543" in database_url
    DATABASES = {
        "default": dj_database_url.parse(
            database_url,
            engine="django.db.backends.postgresql",
            conn_max_age=0 if is_pooler else 600,
            ssl_require=True,
        )
    }
    DATABASES["default"].setdefault("OPTIONS", {})
    DATABASES["default"]["OPTIONS"]["sslmode"] = "require"
    if is_pooler:
        DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
            # The dev server is multi-threaded: wait for the writer instead of
            # raising "database is locked" when two requests overlap.
            "OPTIONS": {"timeout": 20},
        }
    }

    # WAL keeps reads working while a write is in flight, which matters because
    # the front end fires several API calls in parallel on every interaction.
    from django.db.backends.signals import connection_created
    from django.dispatch import receiver

    @receiver(connection_created)
    def _configure_sqlite(sender, connection, **kwargs):
        if connection.vendor != "sqlite":
            return
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA busy_timeout=15000;")
            cursor.execute("PRAGMA foreign_keys=ON;")

# Supabase API / Storage credentials (optional)
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

# --------------------------------------------------------------------------- #
# Athar AI assistant
# --------------------------------------------------------------------------- #
# The assistant works fully offline (see core/ai.py). Set AI_API_KEY to upgrade
# to any OpenAI-compatible endpoint; failures always fall back to the local
# engine, so a bad key can never break the product.
AI_API_KEY = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY", "")
AI_BASE_URL = os.getenv("AI_BASE_URL") or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")

AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "core" / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Uploads: profile pictures and post images are processed and stored in the
# database, so only in-memory size guards are needed here.
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 8 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000

# Keep the dev server friendly to both embedded iframe preview and local HTTP development.
# NOTE: django.middleware.clickjacking.XFrameOptionsMiddleware is intentionally not
# installed so the app can be embedded in the Arena preview iframe.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", False)
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", False)
SESSION_SAVE_EVERY_REQUEST = True
SECURE_REFERRER_POLICY = "same-origin"

CSRF_TRUSTED_ORIGINS = [
    "https://*.e2b.app",
    "http://*.e2b.app",
    "https://*.e2b.dev",
    "http://*.e2b.dev",
    "https://*.arena.ai",
    "https://arena.ai",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://0.0.0.0:8000",
]
extra_origins = os.getenv("CSRF_TRUSTED_ORIGINS", "")
if extra_origins:
    CSRF_TRUSTED_ORIGINS.extend(origin.strip() for origin in extra_origins.split(",") if origin.strip())
