"""Local verification of access tokens issued by the auth service."""

from dataclasses import dataclass
from datetime import UTC, datetime

import jwt

from shared_auth.contract import (
    ACCESS_TOKEN_TYPE,
    ALGORITHM,
    REQUIRED_ACCESS_CLAIMS,
    Claim,
    known_roles,
)


class InvalidToken(Exception):
    """The token is malformed, expired, wrongly signed, or not an access token
    for this audience and issuer."""


@dataclass(frozen=True)
class VerifiedToken:
    subject: str
    roles: tuple[str, ...]
    token_id: str
    issued_at: datetime
    expires_at: datetime


def verify_token(
    token: str, *, public_key: str, issuer: str, audience: str
) -> VerifiedToken:
    """Verify an access token's RS256 signature, expiry, issuer and audience,
    and that every contract claim is present. Only RS256 is accepted, so
    unsigned tokens and algorithm substitution (e.g. HS256 keyed with the
    public key) are rejected."""
    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=[ALGORITHM],
            issuer=issuer,
            audience=audience,
            options={"require": list(REQUIRED_ACCESS_CLAIMS)},
        )
    except jwt.PyJWTError as error:
        raise InvalidToken(str(error)) from error

    if payload[Claim.TOKEN_TYPE] != ACCESS_TOKEN_TYPE:
        raise InvalidToken("Not an access token.")
    subject, roles = payload[Claim.SUBJECT], payload[Claim.ROLES]
    if not isinstance(subject, str) or not subject:
        raise InvalidToken("Invalid subject.")
    if not isinstance(roles, list) or not all(isinstance(r, str) for r in roles):
        raise InvalidToken("Invalid roles claim.")
    token_id = payload[Claim.TOKEN_ID]
    if not isinstance(token_id, str) or not token_id:
        raise InvalidToken("Invalid token ID.")

    return VerifiedToken(
        subject=subject,
        roles=known_roles(roles),
        token_id=token_id,
        issued_at=datetime.fromtimestamp(payload[Claim.ISSUED_AT], tz=UTC),
        expires_at=datetime.fromtimestamp(payload[Claim.EXPIRES_AT], tz=UTC),
    )
