"""Phase 1 foundation tests for the auth service."""

import os
import tomllib
from importlib.metadata import version
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection

from accounts.models import User

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_health_endpoint_reports_ok(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_tests_run_against_the_auth_postgresql_database():
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        (database,) = cursor.fetchone()

    assert connection.vendor == "postgresql"
    assert settings.DATABASES["default"]["HOST"] == "auth-db"
    assert database == f"test_{os.environ['POSTGRES_DB']}"


def test_custom_user_model_is_active():
    assert settings.AUTH_USER_MODEL == "accounts.User"
    assert get_user_model() is User


@pytest.mark.django_db
def test_default_user_table_was_never_created():
    tables = connection.introspection.table_names()

    assert "accounts_user" in tables
    assert "auth_user" not in tables


@pytest.mark.django_db
def test_wordpress_user_id_is_a_unique_source_identity():
    User.objects.create_user(username="first", wp_user_id=7)

    with pytest.raises(IntegrityError):
        User.objects.create_user(username="second", wp_user_id=7)


@pytest.mark.django_db
def test_accounts_created_outside_the_import_need_no_wordpress_id():
    User.objects.create_user(username="operator-a")
    User.objects.create_user(username="operator-b")

    assert User.objects.filter(wp_user_id__isnull=True).count() == 2


def test_auth_service_holds_the_private_signing_key():
    assert settings.JWT_PRIVATE_KEY


def test_shared_auth_is_installed_at_the_pinned_version():
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())
    pins = [
        dep.split("==", 1)[1]
        for dep in pyproject["project"]["dependencies"]
        if dep.startswith("shared-auth==")
    ]

    assert pins == [version("shared-auth")]
