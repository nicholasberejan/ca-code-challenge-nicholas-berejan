"""Login, refresh, logout and session revocation through the real endpoints.

Access tokens are checked with shared_auth.verify_token, the same code the
main app uses, keyed with this service's public key.
"""

import time

import jwt
import pytest
from django.conf import settings
from django.contrib.auth.models import Group
from rest_framework_simplejwt.tokens import RefreshToken
from shared_auth.tokens import InvalidToken, verify_token

from accounts.models import User
from accounts.roles import set_role
from accounts.tokens import TokenRejected, _consume, issue_tokens, revoke_all_sessions

pytestmark = pytest.mark.django_db

PASSWORD = "correct horse battery staple"


def make_user(username="editor", role="editor", **fields) -> User:
    user = User.objects.create_user(username=username, password=PASSWORD, **fields)
    user.groups.add(Group.objects.get(name=role))
    return user


def post(client, path, body):
    return client.post(path, body, content_type="application/json")


def login(client, username="editor", password=PASSWORD):
    return post(client, "/api/token/", {"username": username, "password": password})


def refresh(client, token):
    return post(client, "/api/token/refresh/", {"refresh": token})


def verify(access: str):
    return verify_token(
        access,
        public_key=settings.JWT_PUBLIC_KEY,
        issuer=settings.JWT_ISSUER,
        audience=settings.JWT_AUDIENCE,
    )


def payload(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


# --- Login ----------------------------------------------------------------------


def test_login_issues_an_rs256_access_token_with_the_contract_claims(client):
    user = make_user()

    response = login(client)

    assert response.status_code == 200
    access = response.json()["access"]
    assert jwt.get_unverified_header(access)["alg"] == "RS256"
    claims = payload(access)
    assert set(claims) == {
        "sub",
        "roles",
        "iss",
        "aud",
        "exp",
        "iat",
        "jti",
        "token_type",
    }
    assert claims["sub"] == str(user.pk)
    assert claims["roles"] == ["editor"]
    assert claims["iss"] == settings.JWT_ISSUER
    assert claims["aud"] == settings.JWT_AUDIENCE
    assert claims["exp"] - claims["iat"] == 300
    assert verify(access).roles == ("editor",)


def test_refresh_token_carries_identity_but_no_roles(client):
    make_user()

    claims = payload(login(client).json()["refresh"])

    assert "roles" not in claims
    assert claims["token_type"] == "refresh"
    assert claims["exp"] - claims["iat"] == 24 * 60 * 60
    with pytest.raises(InvalidToken):
        verify(login(client).json()["refresh"])  # never accepted as an access token


def test_only_application_roles_reach_the_token(client):
    user = make_user(role="reader")
    user.groups.add(Group.objects.create(name="staff-lounge"))

    assert payload(login(client).json()["access"])["roles"] == ["reader"]


def test_wrong_password_unknown_user_and_inactive_user_are_rejected(client):
    make_user()
    make_user(username="inactive", is_active=False)

    for username, password in [
        ("editor", "wrong"),
        ("nobody", PASSWORD),
        ("inactive", PASSWORD),
    ]:
        response = login(client, username, password)
        assert response.status_code == 401
        assert "access" not in response.json()


# --- Refresh ---------------------------------------------------------------------


def test_refresh_rotates_and_the_old_token_cannot_be_replayed(client):
    make_user()
    first = login(client).json()

    rotated = refresh(client, first["refresh"])
    assert rotated.status_code == 200
    second = rotated.json()
    assert second["refresh"] != first["refresh"]
    assert verify(second["access"]).roles == ("editor",)

    assert refresh(client, first["refresh"]).status_code == 401
    assert refresh(client, second["refresh"]).status_code == 200


def test_refresh_uses_current_roles_after_demotion(client):
    user = make_user()
    tokens = login(client).json()
    assert verify(tokens["access"]).roles == ("editor",)

    set_role(user, "reader")
    refreshed = refresh(client, tokens["refresh"]).json()

    assert verify(refreshed["access"]).roles == ("reader",)
    assert "roles" not in payload(refreshed["refresh"])
    # Rotating again cannot bring the old role back.
    again = refresh(client, refreshed["refresh"]).json()
    assert verify(again["access"]).roles == ("reader",)


def test_refresh_uses_current_roles_after_promotion(client):
    user = make_user(role="reader")
    tokens = login(client).json()

    set_role(user, "editor")

    assert verify(refresh(client, tokens["refresh"]).json()["access"]).roles == (
        "editor",
    )


def test_deactivated_user_cannot_refresh_but_issued_access_stays_valid(client):
    user = make_user()
    tokens = login(client).json()

    User.objects.filter(pk=user.pk).update(is_active=False)

    response = refresh(client, tokens["refresh"])
    assert response.status_code == 401
    assert "access" not in response.json()
    # Accepted staleness: the access token works until it expires.
    assert verify(tokens["access"]).subject == str(user.pk)
    # Reactivating does not revive the refused token.
    User.objects.filter(pk=user.pk).update(is_active=True)
    assert refresh(client, tokens["refresh"]).status_code == 401


def test_deleted_user_cannot_refresh(client):
    user = make_user()
    tokens = login(client).json()
    user.delete()

    assert refresh(client, tokens["refresh"]).status_code == 401


@pytest.mark.parametrize(
    ("token", "status"), [("", 400), ("garbage", 401), ("a.b.c", 401)]
)
def test_malformed_refresh_tokens_are_rejected(client, token, status):
    assert refresh(client, token).status_code == status


def test_a_refresh_token_can_be_consumed_only_once_even_if_already_verified():
    # Two simultaneous refreshes both pass RefreshToken()'s blacklist check
    # before either blacklists the token; the locked re-check in _consume is
    # what lets only one of them through.
    make_user()
    raw = issue_tokens(User.objects.get()).refresh
    first, second = RefreshToken(raw), RefreshToken(raw)

    _consume(first)

    with pytest.raises(TokenRejected, match="already used"):
        _consume(second)


def test_access_token_is_not_accepted_for_refresh(client):
    make_user()

    assert refresh(client, login(client).json()["access"]).status_code == 401


def test_expired_refresh_token_is_rejected(client, settings):
    make_user()
    tokens = login(client).json()
    claims = payload(tokens["refresh"])
    expired = jwt.encode(
        {**claims, "exp": int(time.time()) - 10},
        settings.JWT_PRIVATE_KEY,
        algorithm="RS256",
    )

    assert refresh(client, expired).status_code == 401


# --- Logout and revocation ------------------------------------------------------------


def test_logout_revokes_the_refresh_token(client):
    make_user()
    tokens = login(client).json()

    assert (
        post(client, "/api/token/logout/", {"refresh": tokens["refresh"]}).status_code
        == 204
    )

    assert refresh(client, tokens["refresh"]).status_code == 401
    assert (
        post(client, "/api/token/logout/", {"refresh": tokens["refresh"]}).status_code
        == 401
    )
    # The access token is stateless and stays valid until it expires.
    assert verify(tokens["access"]).roles == ("editor",)


def test_revoking_all_sessions_blocks_every_refresh_token_of_that_user(client):
    user = make_user()
    other = make_user(username="other")
    sessions = [login(client).json() for _ in range(3)]
    other_session = login(client, "other").json()

    assert revoke_all_sessions(user) == 3

    for session in sessions:
        assert refresh(client, session["refresh"]).status_code == 401
        assert verify(session["access"]).subject == str(user.pk)
    assert refresh(client, other_session["refresh"]).status_code == 200
    assert other.is_active


def test_admin_action_revokes_sessions(client):
    admin = make_user(username="op", is_staff=True, is_superuser=True)
    user = make_user(username="target")
    session = login(client, "target").json()
    client.force_login(admin)

    response = client.post(
        "/admin/accounts/user/",
        {"action": "revoke_sessions", "_selected_action": [user.pk]},
    )

    assert response.status_code == 302
    assert refresh(client, session["refresh"]).status_code == 401
