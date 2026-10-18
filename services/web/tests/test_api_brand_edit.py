"""PATCH /api/brands/<slug>/: local token verification, editor-only writes,
short_description only (docs/decisions.md §4, §7).

Tokens here are signed with a throwaway test key that the test settings
trust, to exercise the verifier's accept/reject rules. The real login and
refresh flow against the auth service is exercised by scripts/verify.sh
(scripts/e2e/auth_flow.py).
"""

import base64
import time
import uuid
from functools import cache
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from django.conf import settings as django_settings
from django.core.exceptions import ImproperlyConfigured

from config.settings import rsa_public_key_from_env
from content.models import Brand
from content.wordpress.importer import import_snapshot

from .factories import make_brand, make_industry
from .snapshots import brand, snapshot

pytestmark = pytest.mark.django_db

ISSUER = "https://auth.test"
AUDIENCE = "web.test"


@cache
def key_pair(name: str) -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private, public


@pytest.fixture(autouse=True)
def trusted_test_key(settings):
    settings.SHARED_AUTH = {
        "PUBLIC_KEY": key_pair("issuer")[1],
        "ISSUER": ISSUER,
        "AUDIENCE": AUDIENCE,
    }


def token(roles: list[str] | None = None, key: str = "issuer", **overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": "7",
        "roles": ["editor"] if roles is None else roles,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 300,
        "jti": uuid.uuid4().hex,
        "token_type": "access",
        **overrides,
    }
    return jwt.encode(claims, key_pair(key)[0], algorithm="RS256")


def patch(client, slug: str, body: Any, auth: str | None = None):
    headers = {} if auth is None else {"HTTP_AUTHORIZATION": auth}
    return client.patch(
        f"/api/brands/{slug}/", data=body, content_type="application/json", **headers
    )


def editor() -> str:
    return f"Bearer {token(['editor'])}"


@pytest.fixture
def acme():
    return make_brand(
        "acme",
        industries=[make_industry("insurance")],
        ratings=[4, 5],
        short_description="Original text.",
    )


# --- Authorization ---------------------------------------------------------------


def test_editor_can_update_the_short_description(client, acme):
    response = patch(client, "acme", {"short_description": "  New text.  "}, editor())

    assert response.status_code == 200
    acme.refresh_from_db()
    assert acme.short_description == "New text."
    assert response.json()["short_description"] == "New text."


def test_response_has_the_listing_row_shape(client, acme):
    body = patch(client, "acme", {"short_description": "New."}, editor()).json()
    listing_row = client.get("/api/brands/").json()["results"][0]

    assert body == listing_row
    assert body["review_count"] == 2
    assert body["average_rating"] == 4.5


def test_reader_is_forbidden(client, acme):
    response = patch(
        client, "acme", {"short_description": "x"}, f"Bearer {token(['reader'])}"
    )

    assert response.status_code == 403
    assert response.json() == {
        "errors": {"detail": ["You do not have permission to perform this action."]}
    }
    acme.refresh_from_db()
    assert acme.short_description == "Original text."


def test_token_without_known_roles_is_forbidden(client, acme):
    response = patch(
        client, "acme", {"short_description": "x"}, f"Bearer {token(['admin'])}"
    )

    assert response.status_code == 403


UNAUTHENTICATED = {
    "no header": None,
    "malformed header": "Bearer",
    "other scheme": "Basic dXNlcjpwYXNz",
    "garbage token": "Bearer not.a.token",
    "expired": f"Bearer {token(exp=int(time.time()) - 10)}",
    "wrong issuer": f"Bearer {token(iss='https://evil.test')}",
    "wrong audience": f"Bearer {token(aud='another-service')}",
    "signed by another key": f"Bearer {token(key='attacker')}",
    "refresh token": f"Bearer {token(token_type='refresh')}",
    "tampered signature": f"Bearer {token()[:-6]}AAAAAA",
}


@pytest.mark.parametrize("auth", UNAUTHENTICATED.values(), ids=UNAUTHENTICATED.keys())
def test_missing_or_invalid_tokens_are_401(client, acme, auth):
    response = patch(client, "acme", {"short_description": "x"}, auth)

    assert response.status_code == 401
    assert response["WWW-Authenticate"] == 'Bearer realm="api"'
    assert set(response.json()["errors"]) == {"detail"}
    acme.refresh_from_db()
    assert acme.short_description == "Original text."


def test_authentication_is_checked_before_the_brand_is_looked_up(client):
    assert patch(client, "missing", {"short_description": "x"}).status_code == 401
    assert (
        patch(client, "missing", {"short_description": "x"}, editor()).status_code
        == 404
    )


def test_public_reads_need_no_token(client, acme):
    assert client.get("/api/brands/").status_code == 200
    assert client.get("/brand/acme/").status_code == 200


# --- Validation ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "field", "message"),
    [
        (
            {"short_description": ""},
            "short_description",
            "This field may not be blank.",
        ),
        (
            {"short_description": "    "},
            "short_description",
            "This field may not be blank.",
        ),
        (
            {"short_description": "x" * 301},
            "short_description",
            "Ensure this field has no more than 300 characters.",
        ),
        ({"short_description": 123}, "short_description", "Must be a string."),
        ({"short_description": None}, "short_description", "Must be a string."),
        ({"short_description": ["a"]}, "short_description", "Must be a string."),
        ({}, "short_description", "This field is required."),
    ],
)
def test_invalid_short_description_is_rejected(client, acme, body, field, message):
    response = patch(client, "acme", body, editor())

    assert response.status_code == 400
    assert response.json() == {"errors": {field: [message]}}
    acme.refresh_from_db()
    assert acme.short_description == "Original text."


def test_exactly_300_characters_after_trimming_is_accepted(client, acme):
    text = "x" * 300

    response = patch(client, "acme", {"short_description": f"   {text}   "}, editor())

    assert response.status_code == 200
    acme.refresh_from_db()
    assert acme.short_description == text


def test_body_must_be_a_json_object(client, acme):
    response = patch(client, "acme", ["short_description"], editor())

    assert response.status_code == 400
    assert response.json() == {"errors": {"detail": ["Expected a JSON object."]}}


@pytest.mark.parametrize(
    "field",
    [
        "name",
        "slug",
        "content",
        "industries",
        "legacy_average_rating",
        "average_rating",
        "review_count",
        "wp_post_id",
        "website_url",
    ],
)
def test_other_fields_cannot_be_changed(client, acme, field):
    before = Brand.objects.filter(pk=acme.pk).values().get()

    response = patch(
        client, "acme", {"short_description": "New.", field: "changed"}, editor()
    )

    assert response.status_code == 400
    assert response.json() == {"errors": {field: ["This field cannot be changed."]}}
    assert Brand.objects.filter(pk=acme.pk).values().get() == before


def test_html_is_stored_as_text_and_escaped_on_pages(client, acme):
    patch(client, "acme", {"short_description": "<strong>Hello</strong>"}, editor())

    acme.refresh_from_db()
    assert acme.short_description == "<strong>Hello</strong>"
    page = client.get("/brand/acme/").content.decode()
    assert "<strong>Hello</strong>" not in page
    assert "&lt;strong&gt;Hello&lt;/strong&gt;" in page


def test_only_the_target_brand_changes(client, acme):
    other = make_brand("other", short_description="Untouched.")

    patch(client, "acme", {"short_description": "New."}, editor())

    other.refresh_from_db()
    assert other.short_description == "Untouched."


# --- Ownership across re-import -----------------------------------------------------


def test_edited_short_description_survives_reimport(client):
    import_snapshot(snapshot())
    slug = Brand.objects.get(wp_post_id=7).slug

    assert (
        patch(client, slug, {"short_description": "Edited."}, editor()).status_code
        == 200
    )
    import_snapshot(snapshot(brands=[brand(excerpt="WordPress excerpt changed.")]))

    assert Brand.objects.get(wp_post_id=7).short_description == "Edited."


# --- Key configuration ---------------------------------------------------------------


def test_web_service_has_only_the_public_key_and_no_auth_database():
    assert not hasattr(django_settings, "JWT_PRIVATE_KEY")
    assert set(django_settings.DATABASES) == {"default", "wordpress"}
    assert "django.contrib.auth" not in django_settings.INSTALLED_APPS


@pytest.mark.parametrize(
    "value",
    ["", "not base64!", "aGVsbG8=", "LS0tLS1CRUdJTiBQVUJMSUMgS0VZLS0tLS0K"],
    ids=["empty", "not base64", "not PEM", "truncated PEM"],
)
def test_a_bad_public_key_is_a_startup_configuration_error(monkeypatch, value):
    monkeypatch.setenv("JWT_PUBLIC_KEY", value)

    with pytest.raises(ImproperlyConfigured, match="JWT_PUBLIC_KEY"):
        rsa_public_key_from_env("JWT_PUBLIC_KEY")


def test_a_missing_public_key_is_a_startup_configuration_error(monkeypatch):
    monkeypatch.delenv("JWT_PUBLIC_KEY", raising=False)

    with pytest.raises(ImproperlyConfigured, match="JWT_PUBLIC_KEY is not set"):
        rsa_public_key_from_env("JWT_PUBLIC_KEY")


def test_a_non_rsa_public_key_is_a_startup_configuration_error(monkeypatch):
    pem = (
        ec.generate_private_key(ec.SECP256R1())
        .public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    monkeypatch.setenv("JWT_PUBLIC_KEY", base64.b64encode(pem).decode())

    with pytest.raises(ImproperlyConfigured, match="not an RSA public key"):
        rsa_public_key_from_env("JWT_PUBLIC_KEY")
