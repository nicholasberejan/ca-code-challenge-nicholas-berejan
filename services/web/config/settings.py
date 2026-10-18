"""Settings for the main web service. All configuration comes from the environment."""

import base64
import binascii
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
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
def rsa_public_key_from_env(name: str) -> str:
    """The base64-encoded PEM public key from the environment, checked at
    startup so a bad key is a configuration error, not a 401 on every
    request."""
    try:
        pem = base64.b64decode(require_env(name), validate=True).decode()
        key = load_pem_public_key(pem.encode())
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise ImproperlyConfigured(
            f"{name} is not a base64-encoded PEM public key."
        ) from error
    if not isinstance(key, RSAPublicKey):
        raise ImproperlyConfigured(f"{name} is not an RSA public key.")
    return pem


JWT_PUBLIC_KEY = rsa_public_key_from_env("JWT_PUBLIC_KEY")
JWT_ISSUER = require_env("JWT_ISSUER")
JWT_AUDIENCE = require_env("JWT_AUDIENCE")

# Local token verification by the shared library (docs/decisions.md §7):
# no call to the auth service, no user table.
SHARED_AUTH = {
    "PUBLIC_KEY": JWT_PUBLIC_KEY,
    "ISSUER": JWT_ISSUER,
    "AUDIENCE": JWT_AUDIENCE,
}

# No django.contrib.auth or admin: the main app stores no user accounts
# (docs/decisions.md §1).
INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "core",
    "content",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": ["django.template.context_processors.request"],
        },
    }
]

# The public API is read-only and needs no authentication. No authentication
# class is configured globally, so public endpoints can never inherit one.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "UNAUTHENTICATED_USER": None,
    # Every DRF error uses the API's {"errors": {...}} shape.
    "EXCEPTION_HANDLER": "core.api_errors.api_exception_handler",
}

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
    },
    # Read-only WordPress source for `import_wordpress` (docs/decisions.md §3).
    # Only needed when the import runs; startup never connects to it. The
    # session is opened read-only, so writes fail even with a writable user.
    "wordpress": {
        "ENGINE": "django.db.backends.mysql",
        "HOST": os.environ.get("WP_DB_HOST", ""),
        "PORT": os.environ.get("WP_DB_PORT", "3306"),
        "NAME": os.environ.get("WP_DB_NAME", ""),
        "USER": os.environ.get("WP_DB_USER", ""),
        "PASSWORD": os.environ.get("WP_DB_PASSWORD", ""),
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": "SET SESSION TRANSACTION READ ONLY",
        },
    },
}
DATABASE_ROUTERS = ["config.routers.WordPressSourceRouter"]

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
