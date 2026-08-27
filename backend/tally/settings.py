import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


SECRET_KEY = env_str("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [h.strip() for h in env_str("DJANGO_ALLOWED_HOSTS", "*").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "documents",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "tally.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

WSGI_APPLICATION = "tally.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env_str("POSTGRES_DB", "tally"),
        "USER": env_str("POSTGRES_USER", "tally"),
        "PASSWORD": env_str("POSTGRES_PASSWORD", "tally"),
        "HOST": env_str("POSTGRES_HOST", "db"),
        "PORT": env_str("POSTGRES_PORT", "5432"),
        # Short statement timeout keeps a stuck worker from holding row locks
        # on financial records forever.
        "OPTIONS": {"options": "-c statement_timeout=30000"},
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 50,
}

# The UI is served by Vite, which proxies /api to this service. CORS is only
# relevant when someone runs the frontend outside of docker compose.
CORS_ALLOW_ALL_ORIGINS = DEBUG
CSRF_TRUSTED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "%(asctime)s %(levelname)-7s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "documents": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# --- Processing pipeline -----------------------------------------------------
PROCESSING = {
    "MAX_ATTEMPTS": env_int("PROCESSING_MAX_ATTEMPTS", 3),
    "RETRY_BASE_SECONDS": env_float("PROCESSING_RETRY_BASE_SECONDS", 2.0),
    "RETRY_MAX_SECONDS": env_float("PROCESSING_RETRY_MAX_SECONDS", 60.0),
    "RETRY_JITTER_SECONDS": env_float("PROCESSING_RETRY_JITTER_SECONDS", 1.0),
    "STALE_JOB_TIMEOUT_SECONDS": env_int("PROCESSING_STALE_JOB_TIMEOUT_SECONDS", 60),
    "WORKER_POLL_INTERVAL_SECONDS": env_float("PROCESSING_WORKER_POLL_INTERVAL_SECONDS", 1.0),
    "REVIEW_CONFIDENCE_THRESHOLD": env_float("PROCESSING_REVIEW_CONFIDENCE_THRESHOLD", 0.85),
}

# --- Simulated AI extraction service ----------------------------------------
AI_SIMULATOR = {
    "WEIGHTS": {
        "success": env_float("AI_SIM_WEIGHT_SUCCESS", 55.0),
        "low_confidence": env_float("AI_SIM_WEIGHT_LOW_CONFIDENCE", 12.0),
        "incomplete": env_float("AI_SIM_WEIGHT_INCOMPLETE", 10.0),
        "arithmetic_mismatch": env_float("AI_SIM_WEIGHT_ARITHMETIC_MISMATCH", 5.0),
        "transient_failure": env_float("AI_SIM_WEIGHT_TRANSIENT_FAILURE", 13.0),
        "permanent_failure": env_float("AI_SIM_WEIGHT_PERMANENT_FAILURE", 5.0),
    },
    "LATENCY_MS": env_int("AI_SIM_LATENCY_MS", 250),
}
