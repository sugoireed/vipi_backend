"""Vipi! platform backend settings. Everything secret comes from environment variables (.env)."""
import os
from pathlib import Path

import dj_database_url
import pymysql

# PyMySQL stands in for mysqlclient (no C build needed); Django checks the mysqlclient version, so report one it accepts.
pymysql.version_info = (2, 2, 1, "final", 0)
pymysql.install_as_MySQLdb()

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader (KEY=value lines) so no extra dependency is needed."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-change-me")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "*").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "rest_framework",
    "rest_framework.authtoken",
    "apps.accounts",
    "apps.billing",
    "apps.fleet",
    "apps.translate",
    "apps.esim",
    "apps.contribute",
    "apps.dashboard",
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
                "apps.dashboard.context.market",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=600
    )
}
if DATABASES["default"].get("ENGINE") == "django.db.backends.mysql":
    DATABASES["default"].setdefault("OPTIONS", {}).update(
        {"charset": "utf8mb4", "init_command": "SET sql_mode='STRICT_TRANS_TABLES'"}
    )

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/admin/login/"

# Password-reset emails from the dashboard. Without SMTP settings, DEBUG prints them to the console.
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND") or (
    "django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
# Which country this deployment serves. The brand is VipiAfrica everywhere ("AFRICA" beside the
# logo); each country has its own domain: vipikenya.com now, Uganda / Tanzania later. VIPI_MARKET=ke|ug|tz.
# vipiafrica.com is reserved for the pan-African hub. Uganda/Tanzania domains are placeholders.
_BRAND = {"brand": "VipiAfrica", "qualifier": "Africa"}
MARKETS = {
    "ke": {**_BRAND, "code": "ke", "country": "Kenya", "domain": "vipikenya.com", "city": "Nairobi"},
    "ug": {**_BRAND, "code": "ug", "country": "Uganda", "domain": "vipiuganda.com", "city": "Kampala"},
    "tz": {**_BRAND, "code": "tz", "country": "Tanzania", "domain": "vipitanzania.com", "city": "Dar es Salaam"},
}
MARKET = MARKETS.get(os.environ.get("VIPI_MARKET", "ke").lower(), MARKETS["ke"])

DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", f"{MARKET['brand']} ops <ops@{MARKET['domain']}>")

# The public marketing site (vipi_site). The dashboard and sign-in pages link back to it.
SITE_URL = os.environ.get("SITE_URL", f"https://{MARKET['domain']}").rstrip("/")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.UserRateThrottle", "rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"user": "120/minute", "anon": "30/minute"},
}

# Uploads: live clips are short WAVs (max ~30 s at 16 kHz ≈ 1 MB).
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024

# --- Vipi! platform settings -------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
# Vipi engine (engine/ in this repo): Riba + Mufti/Risto. Empty URL = Gemini only.
VIPI_ENGINE_URL = os.environ.get("VIPI_ENGINE_URL", "")
VIPI_ENGINE_KEY = os.environ.get("VIPI_ENGINE_KEY", "")
VIPI_ENGINE_TIMEOUT = float(os.environ.get("VIPI_ENGINE_TIMEOUT", "25"))
FREE_DAILY_TRANSLATIONS = int(os.environ.get("FREE_DAILY_TRANSLATIONS", "10"))
MAX_CLIP_SECONDS = int(os.environ.get("MAX_CLIP_SECONDS", "30"))
# Talk clips for /contribute/ (transcripts + meanings), cut by sheng_dataset/scrapers/sheng_radio_talk.py
TRANSCRIPT_CLIPS_ROOT = os.environ.get("TRANSCRIPT_CLIPS_ROOT") or str(BASE_DIR.parent / "sheng_dataset" / "raw" / "radio")
USD_TO_KES = float(os.environ.get("USD_TO_KES", "129"))

MPESA = {
    "ENV": os.environ.get("MPESA_ENV", "sandbox"),  # sandbox | production
    "CONSUMER_KEY": os.environ.get("MPESA_CONSUMER_KEY", ""),
    "CONSUMER_SECRET": os.environ.get("MPESA_CONSUMER_SECRET", ""),
    "SHORTCODE": os.environ.get("MPESA_SHORTCODE", "174379"),
    "PASSKEY": os.environ.get("MPESA_PASSKEY", ""),
    "CALLBACK_URL": os.environ.get("MPESA_CALLBACK_URL", ""),
    # Shared secret appended to the callback URL (?k=...) so random posts are rejected.
    "CALLBACK_SECRET": os.environ.get("MPESA_CALLBACK_SECRET", ""),
}

ESIM = {
    "PROVIDER": os.environ.get("ESIM_PROVIDER", "sandbox"),  # sandbox | airalo
    "AIRALO_BASE_URL": os.environ.get("AIRALO_BASE_URL", "https://sandbox-partners-api.airalo.com"),
    "AIRALO_CLIENT_ID": os.environ.get("AIRALO_CLIENT_ID", ""),
    "AIRALO_CLIENT_SECRET": os.environ.get("AIRALO_CLIENT_SECRET", ""),
}

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"vipi": {"handlers": ["console"], "level": "INFO"}},
}
