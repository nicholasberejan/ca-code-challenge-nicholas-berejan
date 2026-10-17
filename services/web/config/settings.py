"""Settings for the main web service. All configuration comes from the environment."""

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

# Token verification (implemented in a later phase). The main app receives only
# the public key; the private signing key belongs to the auth service.
JWT_PUBLIC_KEY = require_env("JWT_PUBLIC_KEY")
JWT_ISSUER = require_env("JWT_ISSUER")
JWT_AUDIENCE = require_env("JWT_AUDIENCE")

# No django.contrib.auth or admin: the main app stores no user accounts
# (docs/decisions.md §1).
INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "core",
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

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

# The frontend build (React bundle and compiled SCSS) is produced by the Node
# stage of this service's Docker image, outside the bind-mounted source tree.
FRONTEND_DIST_DIR = Path(os.environ.get("FRONTEND_DIST_DIR", "/opt/frontend-dist"))
STATIC_URL = "static/"
STATICFILES_DIRS = [("frontend", FRONTEND_DIST_DIR)]
