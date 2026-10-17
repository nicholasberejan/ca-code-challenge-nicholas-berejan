"""Settings for the auth service. All configuration comes from the environment."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ImproperlyConfigured(
            f"Environment variable {name} is not set. Copy .env.example to .env."
        )
    return value


SECRET_KEY = require_env("DJANGO_SECRET_KEY")
DEBUG = os.environ.get("DJANGO_DEBUG", "") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# Token issuance (implemented in a later phase). Only this service holds the
# private signing key.
JWT_PRIVATE_KEY = require_env("JWT_PRIVATE_KEY")
JWT_PUBLIC_KEY = require_env("JWT_PUBLIC_KEY")
JWT_ISSUER = require_env("JWT_ISSUER")
JWT_AUDIENCE = require_env("JWT_AUDIENCE")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "accounts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": require_env("POSTGRES_HOST"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "NAME": require_env("POSTGRES_DB"),
        "USER": require_env("POSTGRES_USER"),
        "PASSWORD": require_env("POSTGRES_PASSWORD"),
    }
}

# Custom user model, established before the first migration
# (docs/decisions.md §7).
AUTH_USER_MODEL = "accounts.User"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True
