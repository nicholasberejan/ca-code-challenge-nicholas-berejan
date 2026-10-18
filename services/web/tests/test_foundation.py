"""Phase 1 foundation tests for the main web service."""

import os
import re
import tomllib
from importlib.metadata import version
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.staticfiles import finders
from django.db import connection

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_health_endpoint_reports_ok(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_endpoint_rejects_writes(client):
    assert client.post("/healthz").status_code == 405


@pytest.mark.django_db
def test_tests_run_against_the_main_postgresql_database():
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        (database,) = cursor.fetchone()

    assert connection.vendor == "postgresql"
    assert settings.DATABASES["default"]["HOST"] == "main-db"
    assert database == f"test_{os.environ['POSTGRES_DB']}"


def test_main_app_has_no_local_user_accounts():
    assert "django.contrib.auth" not in settings.INSTALLED_APPS
    assert "django.contrib.admin" not in settings.INSTALLED_APPS


def test_web_service_never_receives_the_private_signing_key():
    assert "JWT_PRIVATE_KEY" not in os.environ
    assert settings.JWT_PUBLIC_KEY


def test_frontend_build_output_is_served_as_static_files():
    assert finders.find("frontend/brand-list.js") is not None
    assert finders.find("frontend/main.css") is not None


def test_shared_auth_is_installed_at_the_pinned_version():
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())
    # e.g. "shared-auth[drf]==0.2.0": an exact pin, optional extras.
    pins = [
        match.group(1)
        for dep in pyproject["project"]["dependencies"]
        if (match := re.fullmatch(r"shared-auth(?:\[[a-z,]+\])?==(\S+)", dep))
    ]

    assert pins == [version("shared-auth")]
