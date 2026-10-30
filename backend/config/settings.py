import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

from django.core.exceptions import ImproperlyConfigured

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-key")
DEBUG = os.environ.get("DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,backend").split(",")

# Producción: nunca arrancar con secretos de ejemplo ni en modo debug
if os.environ.get("DJANGO_ENV") == "production":
    weak = {"", "dev-insecure-key", "cambiar-en-produccion", "odonto"}
    if DEBUG or SECRET_KEY in weak or len(SECRET_KEY) < 40 or os.environ.get("POSTGRES_PASSWORD", "odonto") in weak:
        raise ImproperlyConfigured("En producción define SECRET_KEY (40+ caracteres), POSTGRES_PASSWORD propia y DEBUG=0")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "rest_framework",
    "rest_framework.authtoken",
    "drf_spectacular",
    "clinica",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "clinica.middleware.TenantMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

if os.environ.get("POSTGRES_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": os.environ["POSTGRES_HOST"],
            "NAME": os.environ.get("POSTGRES_DB", "odonto"),
            "USER": os.environ.get("POSTGRES_USER", "odonto"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "odonto"),
        }
    }
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_USER_MODEL = "clinica.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "es-ec"
TIME_ZONE = "America/Guayaquil"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["clinica.auth.ExpiringTokenAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_THROTTLE_RATES": {"anon": "10/min", "login": "10/min", "mfa": "10/min"},
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}
SPECTACULAR_SETTINGS = {"TITLE": "Odonto DM API", "VERSION": "1.0.0"}

NOTE_LOCK_HOURS = int(os.environ.get("NOTE_LOCK_HOURS", "24"))  # RF-05
SESSION_IDLE_MINUTES = int(os.environ.get("SESSION_IDLE_MINUTES", "15"))  # RNF-05
MAX_DISCOUNT_PCT = int(os.environ.get("MAX_DISCOUNT_PCT", "15"))  # RF-07: descuento autorizado
MFA_REQUIRED = os.environ.get("MFA_REQUIRED", "1") == "1"  # RNF-05: segundo factor obligatorio
MFA_ISSUER = "Odonto DM"

LOGGING = {
    "version": 1,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"notificaciones": {"handlers": ["console"], "level": "INFO"}},
}
