"""Settings for the auth service. All configuration comes from the environment."""

import base64
import binascii
import os
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from shared_auth.contract import ALGORITHM, Claim

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


# Token issuance. Only this service holds the private signing key. Keys are
# base64-encoded PEM in the environment (see .env.example).
def pem_from_env(name: str) -> str:
    try:
        return base64.b64decode(require_env(name), validate=True).decode()
    except (binascii.Error, UnicodeDecodeError) as error:
        raise ImproperlyConfigured(f"{name} is not base64-encoded PEM.") from error


JWT_PRIVATE_KEY = pem_from_env("JWT_PRIVATE_KEY")
JWT_PUBLIC_KEY = pem_from_env("JWT_PUBLIC_KEY")
JWT_ISSUER = require_env("JWT_ISSUER")
JWT_AUDIENCE = require_env("JWT_AUDIENCE")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "accounts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

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
    }
]

STATIC_URL = "static/"

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
    # Read-only WordPress source for `import_wordpress_users`
    # (docs/decisions.md §3). Only needed when the import runs; the session is
    # opened read-only, so writes fail even with a writable user.
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

# The first hasher is used for new and upgraded passwords. The WordPress
# hasher only verifies migrated `$wp$` hashes; Django re-hashes those with
# the first hasher on the user's next successful login (docs/decisions.md §7).
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "accounts.hashers.WordPressPasswordHasher",
]

# The token API needs no authentication of its own; credentials or refresh
# tokens are in the request bodies.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
}

# Token format (docs/decisions.md §7). Tokens are created by
# accounts/tokens.py, not SimpleJWT's views: roles are added to access tokens
# from the database and are never stored in refresh tokens.
SIMPLE_JWT = {
    "ALGORITHM": ALGORITHM,
    "SIGNING_KEY": JWT_PRIVATE_KEY,
    "VERIFYING_KEY": JWT_PUBLIC_KEY,
    "ISSUER": JWT_ISSUER,
    "AUDIENCE": JWT_AUDIENCE,
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=5),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": Claim.SUBJECT,
    "JTI_CLAIM": Claim.TOKEN_ID,
    "TOKEN_TYPE_CLAIM": Claim.TOKEN_TYPE,
    "UPDATE_LAST_LOGIN": False,
}

# Custom user model, established before the first migration
# (docs/decisions.md §7).
AUTH_USER_MODEL = "accounts.User"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True
