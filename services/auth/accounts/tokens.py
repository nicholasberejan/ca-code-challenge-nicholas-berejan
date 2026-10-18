"""Issuing, rotating and revoking tokens (docs/decisions.md §7).

Refresh tokens carry only the user's identity. Every access token's roles are
read from the database when it is issued, so a role change or deactivation
takes effect at the next refresh. SimpleJWT's own refresh is not used: it
copies claims from the old refresh token into the new tokens.
"""

from dataclasses import dataclass

from django.db import transaction
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
from shared_auth.contract import Claim

from accounts.models import User
from accounts.roles import roles_of


class TokenRejected(Exception):
    """The refresh token is invalid, expired, already used or revoked, or its
    user can no longer obtain tokens."""


@dataclass(frozen=True)
class TokenPair:
    access: str
    refresh: str


def access_token_for(user: User) -> AccessToken:
    token = AccessToken.for_user(user)
    token[Claim.ROLES] = roles_of(user)
    return token


def issue_tokens(user: User) -> TokenPair:
    """A fresh pair. The refresh token is recorded as outstanding so it can
    be blacklisted later."""
    refresh = RefreshToken.for_user(user)
    return TokenPair(access=str(access_token_for(user)), refresh=str(refresh))


def _verified_refresh(raw: str) -> RefreshToken:
    try:
        # Checks signature, expiry, issuer, audience, token type, blacklist.
        return RefreshToken(raw)
    except TokenError as error:
        raise TokenRejected(str(error)) from error


def _consume(refresh: RefreshToken) -> None:
    """Blacklist the refresh token, or reject it if that already happened.
    The row lock makes two concurrent uses of one token resolve to one."""
    try:
        outstanding = OutstandingToken.objects.select_for_update().get(
            jti=refresh[Claim.TOKEN_ID]
        )
    except OutstandingToken.DoesNotExist as error:
        raise TokenRejected("Unknown refresh token.") from error
    _, created = BlacklistedToken.objects.get_or_create(token=outstanding)
    if not created:
        raise TokenRejected("Refresh token already used.")


def rotate(raw_refresh: str) -> TokenPair:
    """Use a refresh token once: it is blacklisted, the user is reloaded, and
    a new pair is issued with the user's current roles."""
    refresh = _verified_refresh(raw_refresh)
    with transaction.atomic():
        _consume(refresh)
        user = User.objects.filter(pk=refresh[Claim.SUBJECT]).first()
        active = user is not None and user.is_active
        pair = issue_tokens(user) if user is not None and active else None
    # Raised after the commit, so a refused token stays blacklisted.
    if pair is None:
        raise TokenRejected("No active account for this token.")
    return pair


def revoke(raw_refresh: str) -> None:
    """Logout: the refresh token can no longer be used."""
    refresh = _verified_refresh(raw_refresh)
    with transaction.atomic():
        _consume(refresh)


def revoke_all_sessions(user: User) -> int:
    """Blacklist every outstanding refresh token of the user; returns how many
    were newly revoked. Access tokens already issued stay valid until they
    expire (at most one access-token lifetime)."""
    revoked = 0
    with transaction.atomic():
        for outstanding in OutstandingToken.objects.filter(user=user):
            _, created = BlacklistedToken.objects.get_or_create(token=outstanding)
            revoked += created
    return revoked
