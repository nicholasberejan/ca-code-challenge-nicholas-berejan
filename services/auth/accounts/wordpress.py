"""WordPress user migration (docs/decisions.md §3, §7).

Reads users straight from the WordPress MariaDB (SELECTs only; the
connection is a read-only session). The import only creates: an account
that already exists (matched by wp_user_id) is never modified, because after
cutover the auth service owns roles, passwords and active status.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

import phpserialize
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.backends.base.base import BaseDatabaseWrapper

from accounts.hashers import encode_wordpress_hash
from accounts.models import User
from accounts.roles import map_wordpress_roles

WORDPRESS_HASH_PREFIX = "$wp$"


@dataclass(frozen=True)
class SourceUser:
    wp_user_id: int
    login: str
    email: str
    password_hash: str
    wordpress_roles: frozenset[str]


class UserImportError(Exception):
    """The import cannot continue; nothing was saved."""


def parse_capabilities(raw: str | None) -> frozenset[str]:
    """WordPress `wp_capabilities` (PHP-serialized {role: bool}) -> roles.
    Anything unreadable yields no roles, which maps to reader."""
    if not raw:
        return frozenset()
    try:
        value = phpserialize.loads(raw.encode(), decode_strings=True)
    except ValueError:
        return frozenset()
    if not isinstance(value, dict):
        return frozenset()
    return frozenset(str(role) for role, granted in value.items() if granted)


def read_users(connection: BaseDatabaseWrapper) -> list[SourceUser]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT u.ID, u.user_login, u.user_email, u.user_pass, m.meta_value
            FROM wp_users u
            LEFT JOIN wp_usermeta m
              ON m.user_id = u.ID AND m.meta_key = 'wp_capabilities'
            ORDER BY u.ID
            """
        )
        return [
            SourceUser(
                wp_user_id=row[0],
                login=row[1],
                email=row[2],
                password_hash=row[3],
                wordpress_roles=parse_capabilities(row[4]),
            )
            for row in cursor.fetchall()
        ]


@dataclass
class UserImportReport:
    created: list[str] = field(default_factory=list)
    unchanged: int = 0
    # (wp_user_id, username) of imported accounts missing from WordPress.
    missing: list[tuple[int, str]] = field(default_factory=list)
    # Usernames created with an unusable password (not a `$wp$` hash).
    unsupported_passwords: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.created)


def import_users(source: Iterable[SourceUser]) -> UserImportReport:
    report = UserImportReport()
    source = sorted(source, key=lambda u: u.wp_user_id)
    with transaction.atomic():
        existing = {
            u.wp_user_id: u for u in User.objects.filter(wp_user_id__isnull=False)
        }
        groups = {g.name: g for g in Group.objects.all()}
        for src in source:
            if src.wp_user_id in existing:
                report.unchanged += 1
                continue
            if User.objects.filter(username=src.login).exists():
                raise UserImportError(
                    f"WordPress user {src.wp_user_id}: username {src.login!r} "
                    "already belongs to an account that was not imported."
                )
            role, is_administrator = map_wordpress_roles(src.wordpress_roles)
            user = User(
                username=src.login,
                email=src.email,
                wp_user_id=src.wp_user_id,
                is_staff=is_administrator,
                is_superuser=is_administrator,
            )
            if src.password_hash.startswith(WORDPRESS_HASH_PREFIX):
                user.password = encode_wordpress_hash(src.password_hash)
            else:
                user.set_unusable_password()
                report.unsupported_passwords.append(src.login)
            user.save()
            user.groups.add(groups[role])
            report.created.append(src.login)

        source_ids = {src.wp_user_id for src in source}
        report.missing = sorted(
            (wp_id, u.username)
            for wp_id, u in existing.items()
            if wp_id not in source_ids
        )
    return report


def format_report(report: UserImportReport) -> str:
    lines = [
        "WordPress user import",
        f"  created    {len(report.created)}",
        f"  unchanged  {report.unchanged}  (existing accounts are never modified)",
        f"  missing    {len(report.missing)}",
    ]
    if report.missing:
        lines.append("Missing from WordPress (kept; deactivate them deliberately):")
        lines.extend(f"  {wp_id} {username}" for wp_id, username in report.missing)
    if report.unsupported_passwords:
        lines.append("Created without a usable password (not a WordPress $wp$ hash):")
        lines.extend(f"  {username}" for username in report.unsupported_passwords)
    return "\n".join(lines)
