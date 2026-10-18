"""Application roles are Django groups named after the shared contract's
roles. Only those groups ever reach a token."""

from django.contrib.auth.models import Group
from shared_auth.contract import ROLE_EDITOR, ROLE_READER, known_roles

from accounts.models import User

WORDPRESS_ADMINISTRATOR = "administrator"


def roles_of(user: User) -> list[str]:
    return list(known_roles(user.groups.values_list("name", flat=True)))


def set_role(user: User, role: str) -> None:
    """Give the user exactly one application role (other groups are kept)."""
    if role not in (ROLE_READER, ROLE_EDITOR):
        raise ValueError(f"Unknown role {role!r}")
    user.groups.remove(*Group.objects.filter(name__in=[ROLE_READER, ROLE_EDITOR]))
    user.groups.add(Group.objects.get(name=role))


def map_wordpress_roles(wordpress_roles: frozenset[str]) -> tuple[str, bool]:
    """(application role, is WordPress administrator). Administrators become
    editors; subscribers and unknown roles become readers."""
    if WORDPRESS_ADMINISTRATOR in wordpress_roles:
        return ROLE_EDITOR, True
    return ROLE_READER, False
