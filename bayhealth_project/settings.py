import logging
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import redis


BASE_DIR = Path(__file__).resolve().parent.parent
RUNNING_ON_RAILWAY = bool(
    os.getenv("RAILWAY_ENVIRONMENT")
    or os.getenv("RAILWAY_PROJECT_ID")
    or os.getenv("RAILWAY_SERVICE_ID")
)


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _env_csv(name: str, default: list[str] | None = None) -> list[str]:
    raw = os.getenv(name, "")
    if not raw:
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]


def _bool_env(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _database_from_url(database_url: str) -> dict:
    parsed = urlparse(database_url)
    scheme = (parsed.scheme or "").split("+", 1)[0].lower()
    if scheme not in {"postgres", "postgresql", "pgsql"}:
        raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed.scheme}")

    options: dict[str, str] = {}
    query_options = {key: values[-1] for key, values in parse_qs(parsed.query).items() if values}
    if query_options.get("sslmode"):
        options["sslmode"] = query_options["sslmode"]
    elif IS_PRODUCTION:
        options["sslmode"] = os.getenv("DB_SSLMODE", "require")

    config = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": parsed.username or "",
        "PASSWORD": parsed.password or "",
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or 5432),
        "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "600")),
    }
    if options:
        config["OPTIONS"] = options
    return config


def _database_from_local_env() -> dict:
    db_engine = os.getenv("DB_ENGINE", "").strip().lower()
    if db_engine in {"django.db.backends.sqlite3", "sqlite", "sqlite3"}:
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(BASE_DIR / os.getenv("DB_NAME", "db.sqlite3")),
            "OPTIONS": {"timeout": int(os.getenv("SQLITE_TIMEOUT", "30"))},
        }

    use_postgres = any(
        os.getenv(name, "").strip()
        for name in ["PGDATABASE", "PGUSER", "PGPASSWORD", "PGHOST", "PGPORT"]
    )
    if not use_postgres and not IS_PRODUCTION:
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(BASE_DIR / os.getenv("DB_NAME", "db.sqlite3")),
            "OPTIONS": {"timeout": int(os.getenv("SQLITE_TIMEOUT", "30"))},
        }

    config = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("PGDATABASE", "bayafya_db"),
        "USER": os.getenv("PGUSER", "postgres"),
        "PASSWORD": os.getenv("PGPASSWORD", ""),
        "HOST": os.getenv("PGHOST", "localhost"),
        "PORT": os.getenv("PGPORT", "5432"),
        "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "600")),
    }
    if IS_PRODUCTION:
        config["OPTIONS"] = {"sslmode": os.getenv("DB_SSLMODE", "require")}
    return config

if not RUNNING_ON_RAILWAY:
    _load_env_file(BASE_DIR / ".env")

RUNNING_RUNSERVER = "runserver" in sys.argv
TESTING = "test" in sys.argv
RAILWAY_ENVIRONMENT = os.getenv("RAILWAY_ENVIRONMENT", "").strip()
DJANGO_ENV = os.getenv(
    "DJANGO_ENV",
    "production" if RAILWAY_ENVIRONMENT else "development",
).lower()
IS_PRODUCTION = DJANGO_ENV == "production" or bool(RAILWAY_ENVIRONMENT)
DEBUG = _bool_env("DJANGO_DEBUG", default=not IS_PRODUCTION)
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-change-me-for-production")

logger = logging.getLogger(__name__)

SITE_URL = (
    os.getenv("SITE_URL", "").strip().rstrip("/")
    or (
        f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN', '').strip()}"
        if os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
        else ""
    )
    or ("http://localhost:8000" if DEBUG else "")
)

ALLOWED_HOSTS = _env_csv("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1"])
if "*" in ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
for extra_host in [
    os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip(),
    os.getenv("RAILWAY_PRIVATE_DOMAIN", "").strip(),
]:
    if extra_host and extra_host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(extra_host)
if IS_PRODUCTION and ".up.railway.app" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(".up.railway.app")

CSRF_TRUSTED_ORIGINS = _env_csv("DJANGO_CSRF_TRUSTED_ORIGINS", [])
for candidate in [SITE_URL]:
    if candidate and candidate not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(candidate)

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "channels",
    "core.apps.CoreConfig",
    "hospital.apps.HospitalConfig",
    "telemedicine.apps.TelemedicineConfig",
    "symptom_checker.apps.SymptomCheckerConfig",
    "pharmacy.apps.PharmacyConfig",
    "mental_health.apps.MentalHealthConfig",
    "ambulance.apps.AmbulanceConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "bayhealth_project.urls"

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
                "core.context_processors.navigation",
            ],
        },
    },
]

WSGI_APPLICATION = "bayhealth_project.wsgi.application"
ASGI_APPLICATION = "bayhealth_project.asgi.application"

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if DATABASE_URL:
    DATABASES = {"default": _database_from_url(DATABASE_URL)}
else:
    DATABASES = {"default": _database_from_local_env()}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = (
    "whitenoise.storage.CompressedManifestStaticFilesStorage"
    if IS_PRODUCTION
    else "whitenoise.storage.CompressedStaticFilesStorage"
)
WHITENOISE_AUTOREFRESH = DEBUG
WHITENOISE_USE_FINDERS = DEBUG

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = IS_PRODUCTION
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = IS_PRODUCTION
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 31536000 if IS_PRODUCTION else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = IS_PRODUCTION
SECURE_HSTS_PRELOAD = IS_PRODUCTION
SECURE_SSL_REDIRECT = IS_PRODUCTION and _bool_env("DJANGO_SECURE_SSL_REDIRECT", default=False)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = IS_PRODUCTION
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "core.User"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "home"

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "BayAfya <00peteromondi@gmail.com>")
EMAIL_FAIL_SILENTLY = _bool_env("EMAIL_FAIL_SILENTLY", default=not IS_PRODUCTION)
EMAIL_HOST = os.getenv("EMAIL_HOST", "").strip()
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "").strip()
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "").strip()
EMAIL_USE_TLS = _bool_env("EMAIL_USE_TLS", default=True)
EMAIL_USE_SSL = _bool_env("EMAIL_USE_SSL", default=False)
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "10"))
BREVO_API_KEY = (
    os.getenv("BREVO_API_KEY", "")
).strip()
if BREVO_API_KEY or (EMAIL_HOST and EMAIL_HOST_USER and EMAIL_HOST_PASSWORD):
    EMAIL_BACKEND = "core.email_backends.BrevoEmailBackend"
elif IS_PRODUCTION:
    logger.warning(
        "Production is running without BREVO_API_KEY or SMTP email credentials. Emails will fall back to the console backend until one of those delivery paths is configured."
    )

GOOGLE_AI_API_KEY = (
    os.getenv("GOOGLE_AI_API_KEY")
    or os.getenv("GEMINI_API_KEY")
    or os.getenv("GOOGLE_API_KEY", "")
)
GOOGLE_AI_API_KEYS = [
    item.strip()
    for item in os.getenv("GOOGLE_AI_API_KEYS", os.getenv("GEMINI_API_KEYS", "")).split(",")
    if item.strip()
]
GEMINI_API_KEYS = GOOGLE_AI_API_KEYS
GEMINI_API_KEY = GOOGLE_AI_API_KEY
GOOGLE_AI_MODEL = os.getenv("GOOGLE_AI_MODEL", os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview"))
GEMINI_MODEL = GOOGLE_AI_MODEL
BAYCARE_ASSISTANT_GEMINI_MODEL = os.getenv("BAYCARE_ASSISTANT_GEMINI_MODEL", GOOGLE_AI_MODEL)
_assistant_candidates_raw = os.getenv(
    "BAYCARE_ASSISTANT_GEMINI_CANDIDATES",
    os.getenv("GEMINI_CANDIDATE_MODELS", BAYCARE_ASSISTANT_GEMINI_MODEL),
)
BAYCARE_ASSISTANT_GEMINI_CANDIDATES = [
    item.strip() for item in str(_assistant_candidates_raw).split(",") if item.strip()
] or [BAYCARE_ASSISTANT_GEMINI_MODEL]
GEMINI_CANDIDATE_MODELS = BAYCARE_ASSISTANT_GEMINI_CANDIDATES

REDIS_URL = os.getenv("REDIS_URL", "").strip()
USE_REDIS_CHANNELS = _bool_env(
    "USE_REDIS_CHANNELS",
    default=bool(IS_PRODUCTION and REDIS_URL),
)

channel_backend = "channels.layers.InMemoryChannelLayer"
channel_config: dict[str, list[str]] = {}
if USE_REDIS_CHANNELS and REDIS_URL:
    try:
        probe_client = redis.Redis.from_url(
            REDIS_URL,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        info = probe_client.info()
        version = str(info.get("redis_version", "")).strip()
        major = int(version.split(".", 1)[0]) if version else 0
        if major >= 7:
            channel_backend = "channels_redis.core.RedisChannelLayer"
            channel_config = {"hosts": [REDIS_URL]}
        else:
            logger.warning(
                "Redis server version %s does not support the channel-layer commands BayAfya needs. Falling back to InMemoryChannelLayer.",
                version or "unknown",
            )
    except Exception as exc:
        logger.warning(
            "Could not connect to Redis at %s for channel layers (%s). Falling back to InMemoryChannelLayer.",
            REDIS_URL,
            exc,
        )

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": channel_backend,
        **({"CONFIG": channel_config} if channel_config else {}),
    }
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        }
    },
    "root": {
        "handlers": ["console"],
        "level": os.getenv("DJANGO_LOG_LEVEL", "INFO"),
    },
}
