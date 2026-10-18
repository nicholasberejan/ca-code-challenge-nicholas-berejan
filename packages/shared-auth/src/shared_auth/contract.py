"""The token contract shared by the issuer (auth service) and the verifier
(main app): signing algorithm, claim names, roles and permissions
(docs/decisions.md §7, §8).

Issuer and audience values are deployment configuration (JWT_ISSUER,
JWT_AUDIENCE); both services read them from the same settings.
"""

from collections.abc import Iterable
from typing import Final

ALGORITHM: Final = "RS256"


class Claim:
    SUBJECT: Final = "sub"
    ROLES: Final = "roles"
    ISSUER: Final = "iss"
    AUDIENCE: Final = "aud"
    EXPIRES_AT: Final = "exp"
    ISSUED_AT: Final = "iat"
    TOKEN_ID: Final = "jti"
    # Distinguishes access from refresh tokens, which share a signing key.
    TOKEN_TYPE: Final = "token_type"


ACCESS_TOKEN_TYPE: Final = "access"

REQUIRED_ACCESS_CLAIMS: Final = (
    Claim.SUBJECT,
    Claim.ROLES,
    Claim.ISSUER,
    Claim.AUDIENCE,
    Claim.EXPIRES_AT,
    Claim.ISSUED_AT,
    Claim.TOKEN_ID,
    Claim.TOKEN_TYPE,
)

ROLE_READER: Final = "reader"
ROLE_EDITOR: Final = "editor"
KNOWN_ROLES: Final = frozenset({ROLE_READER, ROLE_EDITOR})


class Permission:
    EDIT_BRAND: Final = "brand.edit"


ROLE_PERMISSIONS: Final[dict[str, frozenset[str]]] = {
    ROLE_READER: frozenset(),
    ROLE_EDITOR: frozenset({Permission.EDIT_BRAND}),
}


def known_roles(names: Iterable[str]) -> tuple[str, ...]:
    """The application roles among `names`, sorted; anything else is dropped,
    so an arbitrary group name never becomes a trusted role."""
    return tuple(sorted(set(names) & KNOWN_ROLES))


def roles_grant(roles: Iterable[str], permission: str) -> bool:
    return any(permission in ROLE_PERMISSIONS.get(role, frozenset()) for role in roles)
