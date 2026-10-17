"""The import_wordpress command: options, output and failure handling.

The command's WordPress read is replaced with an in-memory snapshot; the real
source is covered by test_wordpress_source.py and by scripts/verify.sh.
"""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from content.management.commands import import_wordpress
from content.models import Brand

from .snapshots import brand, review, snapshot

pytestmark = pytest.mark.django_db


@pytest.fixture
def source(monkeypatch):
    current = {"snapshot": snapshot()}
    monkeypatch.setattr(
        import_wordpress, "read_snapshot", lambda connection: current["snapshot"]
    )
    return current


def run(*args):
    out = StringIO()
    call_command("import_wordpress", *args, stdout=out)
    return out.getvalue()


def test_command_imports_and_prints_a_summary(source):
    output = run()

    assert Brand.objects.count() == 1
    assert "WordPress content import" in output
    assert "  brands             1        0          0        0" in output


def test_expect_unchanged_passes_when_nothing_changes(source):
    run()

    run("--expect-unchanged")


def test_expect_unchanged_fails_and_rolls_back_when_something_changes(source):
    run()
    source["snapshot"] = snapshot(brands=[brand(title="Renamed")])

    with pytest.raises(CommandError, match="expect-unchanged"):
        run("--expect-unchanged")

    assert Brand.objects.get().name == "Acme Insurance Co."


def test_prune_flag_deletes_and_reports(source):
    run()
    source["snapshot"] = snapshot(brands=[], reviews=[])

    output = run("--prune")

    assert not Brand.objects.exists()
    assert "deleted" in output
    assert "Missing from WordPress (deleted (--prune)):" in output


def test_invalid_source_data_aborts_with_a_clear_error(source):
    source["snapshot"] = snapshot(reviews=[review(rating="ten")])

    with pytest.raises(CommandError, match="nothing was saved"):
        run()

    assert not Brand.objects.exists()
