"""The optional DRF classes, against a minimal Django configuration defined
here (not either service's project)."""

from typing import Any

import django
import pytest
from django.conf import settings

from tests.keys import AUDIENCE, ISSUER, claims, key_pair, sign

if not settings.configured:
    settings.configure(
        SECRET_KEY="test-only",
        INSTALLED_APPS=[],
        REST_FRAMEWORK={"UNAUTHENTICATED_USER": None},
        SHARED_AUTH={
            "PUBLIC_KEY": key_pair()[1],
            "ISSUER": ISSUER,
            "AUDIENCE": AUDIENCE,
        },
    )
    django.setup()

from rest_framework.response import Response  # noqa: E402
from rest_framework.test import APIRequestFactory  # noqa: E402
from rest_framework.views import APIView  # noqa: E402

from shared_auth.drf import CanEditBrands, JWTAuthentication  # noqa: E402
from shared_auth.principal import Principal  # noqa: E402


class EditView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [CanEditBrands]

    def patch(self, request: Any) -> Response:
        user = request.user
        assert isinstance(user, Principal)
        return Response({"subject": user.subject, "roles": list(user.roles)})


def patch(authorization: str | None) -> Any:
    headers = {} if authorization is None else {"HTTP_AUTHORIZATION": authorization}
    request = APIRequestFactory().patch("/", {}, format="json", **headers)
    return EditView.as_view()(request)


def test_editor_is_allowed() -> None:
    response = patch(f"Bearer {sign(claims(sub='9', roles=['editor']))}")

    assert response.status_code == 200
    assert response.data == {"subject": "9", "roles": ["editor"]}


def test_reader_is_authenticated_but_forbidden() -> None:
    response = patch(f"Bearer {sign(claims(roles=['reader']))}")

    assert response.status_code == 403


def test_token_without_roles_is_forbidden() -> None:
    assert patch(f"Bearer {sign(claims(roles=[]))}").status_code == 403


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "",
        "Bearer",
        "Bearer a b",
        "Token abc",
        "bearer " + sign(claims()),
        "Bearer not-a-token",
        "Bearer " + sign(claims(), key="attacker"),
        "Bearer " + sign(claims(aud="other")),
    ],
    ids=[
        "missing",
        "empty",
        "no token",
        "extra parts",
        "other scheme",
        "lowercase scheme",
        "garbage",
        "wrong key",
        "wrong audience",
    ],
)
def test_missing_or_invalid_credentials_are_401(authorization: str | None) -> None:
    response = patch(authorization)

    assert response.status_code == 401
    assert response["WWW-Authenticate"] == 'Bearer realm="api"'
