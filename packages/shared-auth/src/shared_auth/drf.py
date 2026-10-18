"""Optional DRF integration (install `shared-auth[drf]`).

Settings: SHARED_AUTH = {"PUBLIC_KEY": <PEM>, "ISSUER": ..., "AUDIENCE": ...}
"""

from typing import Any

from django.conf import settings
from rest_framework import authentication, exceptions, permissions
from rest_framework.request import Request

from shared_auth.contract import Permission
from shared_auth.principal import Principal
from shared_auth.tokens import InvalidToken, verify_token

KEYWORD = "Bearer"


class JWTAuthentication(authentication.BaseAuthentication):
    """Authenticates `Authorization: Bearer <access token>` locally, with the
    public key; never calls the auth service. No header: anonymous (the
    permission then answers 401). A bad header or token: 401."""

    def authenticate(self, request: Request) -> tuple[Principal, Any] | None:
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header:
            return None
        parts = header.split()
        if len(parts) != 2 or parts[0] != KEYWORD:
            raise exceptions.AuthenticationFailed(
                "Authorization header must be 'Bearer <token>'."
            )
        config = settings.SHARED_AUTH
        try:
            token = verify_token(
                parts[1],
                public_key=config["PUBLIC_KEY"],
                issuer=config["ISSUER"],
                audience=config["AUDIENCE"],
            )
        except InvalidToken:
            raise exceptions.AuthenticationFailed("Invalid or expired token.") from None
        return Principal.from_token(token), token

    def authenticate_header(self, request: Request) -> str:
        # Its presence makes DRF answer 401 (not 403) when unauthenticated.
        return f'{KEYWORD} realm="api"'


class CanEditBrands(permissions.BasePermission):
    """Editors only: 403 for an authenticated caller without the role."""

    def has_permission(self, request: Request, view: Any) -> bool:
        user = request.user
        return isinstance(user, Principal) and user.has_permission(
            Permission.EDIT_BRAND
        )
