from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError, connections, transaction

from accounts.wordpress import UserImportError, format_report, import_users, read_users


class Command(BaseCommand):
    help = (
        "Create auth accounts for WordPress users (username, email, password "
        "hash, role). Existing accounts are never modified. Safe to re-run."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--expect-unchanged",
            action="store_true",
            help="Fail, and roll back, if the import would create anything. "
            "Used by scripts/verify.sh.",
        )

    def handle(self, *args: object, expect_unchanged: bool, **options: object) -> None:
        if not settings.DATABASES["wordpress"]["HOST"]:
            raise CommandError("WP_DB_HOST is not set. Copy .env.example to .env.")
        try:
            source = read_users(connections["wordpress"])
        except DatabaseError as error:
            raise CommandError(
                f"Cannot read the WordPress database: {error}. "
                "Is it running? (docker compose up -d db)"
            ) from error
        finally:
            connections["wordpress"].close()

        try:
            with transaction.atomic():
                report = import_users(source)
                self.stdout.write(format_report(report))
                if expect_unchanged and report.changed:
                    raise CommandError(
                        "--expect-unchanged: the import would create accounts "
                        "(rolled back)."
                    )
        except UserImportError as error:
            raise CommandError(f"Import aborted, nothing was saved: {error}") from error
