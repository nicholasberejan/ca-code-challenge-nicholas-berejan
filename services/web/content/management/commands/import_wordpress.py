from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError, connections, transaction

from content.wordpress.importer import SourceDataError, format_report, import_snapshot
from content.wordpress.source import read_snapshot


class Command(BaseCommand):
    help = (
        "Import published WordPress content (industries, brands, reviewers, "
        "reviews) from the WordPress database. Safe to re-run."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--prune",
            action="store_true",
            help="Delete content that no longer exists in WordPress.",
        )
        parser.add_argument(
            "--expect-unchanged",
            action="store_true",
            help=(
                "Fail, and roll back, if the import would create, update or "
                "delete anything. Used by scripts/verify.sh."
            ),
        )

    def handle(
        self, *args: object, prune: bool, expect_unchanged: bool, **options: object
    ) -> None:
        if not settings.DATABASES["wordpress"]["HOST"]:
            raise CommandError("WP_DB_HOST is not set. Copy .env.example to .env.")
        try:
            snapshot = read_snapshot(connections["wordpress"])
        except DatabaseError as error:
            raise CommandError(
                f"Cannot read the WordPress database: {error}. "
                "Is it running? (docker compose up -d db)"
            ) from error
        finally:
            connections["wordpress"].close()

        try:
            with transaction.atomic():
                report = import_snapshot(snapshot, prune=prune)
                self.stdout.write(format_report(report))
                if expect_unchanged and report.changed:
                    raise CommandError(
                        "--expect-unchanged: the import would change content "
                        "(rolled back)."
                    )
        except SourceDataError as error:
            raise CommandError(f"Import aborted, nothing was saved: {error}") from error
