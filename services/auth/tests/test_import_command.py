"""The import_wordpress_users command: options, output and failure handling.

The WordPress read is replaced with in-memory users; the real source is
covered by tests reading the seed database and by scripts/verify.sh.
"""

from io import StringIO

import pytest
from django.conf import settings as django_settings
from django.core.management import CommandError, call_command

from accounts.management.commands import import_wordpress_users
from accounts.models import User
from accounts.wordpress import SourceUser

pytestmark = pytest.mark.django_db

WP_HASH = "$wp$2y$10$" + "a" * 53


def user(wp_id: int, login: str) -> SourceUser:
    return SourceUser(
        wp_id, login, f"{login}@example.com", WP_HASH, frozenset({"subscriber"})
    )


@pytest.fixture
def source(monkeypatch):
    current = {"users": [user(2, "sarah_k")]}
    monkeypatch.setattr(
        import_wordpress_users, "read_users", lambda connection: current["users"]
    )
    return current


def run(*args):
    out = StringIO()
    call_command("import_wordpress_users", *args, stdout=out)
    return out.getvalue()


def test_command_imports_and_prints_a_summary(source):
    output = run()

    assert User.objects.filter(username="sarah_k").exists()
    assert "created    1" in output


def test_expect_unchanged_fails_and_rolls_back_when_users_would_be_created(source):
    with pytest.raises(CommandError, match="expect-unchanged"):
        run("--expect-unchanged")

    assert not User.objects.exists()


def test_expect_unchanged_passes_when_nothing_is_new(source):
    run()

    output = run("--expect-unchanged")

    assert "created    0" in output
    assert "unchanged  1" in output


def test_expect_unchanged_still_fails_for_one_new_user(source):
    run()
    source["users"] = [user(2, "sarah_k"), user(3, "mike_t")]

    with pytest.raises(CommandError, match="expect-unchanged"):
        run("--expect-unchanged")

    assert not User.objects.filter(username="mike_t").exists()


def test_import_errors_abort_with_a_clear_message(source):
    User.objects.create_user(username="sarah_k", password="x")

    with pytest.raises(CommandError, match="nothing was saved"):
        run()


def test_missing_wordpress_host_is_a_clear_error(source, monkeypatch):
    monkeypatch.setitem(django_settings.DATABASES["wordpress"], "HOST", "")

    with pytest.raises(CommandError, match="WP_DB_HOST"):
        run()
