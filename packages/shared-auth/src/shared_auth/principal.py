"""The authenticated caller, built from a verified access token. It is never
stored: the main app keeps no user accounts (docs/decisions.md §1)."""

from dataclasses import dataclass

from shared_auth.contract import roles_grant
from shared_auth.tokens import VerifiedToken


@dataclass(frozen=True)
class Principal:
    subject: str
    roles: tuple[str, ...]
    token_id: str

    is_authenticated = True
    is_anonymous = False

    @classmethod
    def from_token(cls, token: VerifiedToken) -> "Principal":
        return cls(subject=token.subject, roles=token.roles, token_id=token.token_id)

    def has_permission(self, permission: str) -> bool:
        return roles_grant(self.roles, permission)
