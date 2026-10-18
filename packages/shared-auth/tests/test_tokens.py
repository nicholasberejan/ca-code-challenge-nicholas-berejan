"""verify_token: what the main app trusts. No Django involved."""

import time
from collections.abc import Callable

import pytest

from shared_auth.tokens import InvalidToken, VerifiedToken, verify_token
from tests.keys import (
    AUDIENCE,
    ISSUER,
    b64,
    claims,
    forge_hs256_with_public_key,
    key_pair,
    sign,
    unsigned,
)


def verify(token: str) -> VerifiedToken:
    return verify_token(
        token, public_key=key_pair()[1], issuer=ISSUER, audience=AUDIENCE
    )


def test_valid_token_is_verified() -> None:
    payload = claims(sub="7", roles=["reader", "editor"])

    verified = verify(sign(payload))

    assert verified.subject == "7"
    assert verified.roles == ("editor", "reader")
    assert verified.token_id == payload["jti"]
    assert int(verified.expires_at.timestamp()) == payload["exp"]


def test_unknown_roles_are_dropped() -> None:
    verified = verify(sign(claims(roles=["editor", "superadmin", "Editor"])))

    assert verified.roles == ("editor",)


def test_token_without_roles_has_no_roles() -> None:
    assert verify(sign(claims(roles=[]))).roles == ()


REJECTED: dict[str, Callable[[], str]] = {
    "expired": lambda: sign(claims(exp=int(time.time()) - 1)),
    "wrong issuer": lambda: sign(claims(iss="https://evil.test")),
    "wrong audience": lambda: sign(claims(aud="other-service")),
    "signed by another key": lambda: sign(claims(), key="attacker"),
    "HS256 keyed with the public key": lambda: forge_hs256_with_public_key(claims()),
    "unsigned (alg none)": lambda: unsigned(claims()),
    "refresh token": lambda: sign(claims(token_type="refresh")),
    "not a JWT": lambda: "not-a-token",
    "empty": lambda: "",
    "missing roles": lambda: sign(claims(roles=None)),
    "missing jti": lambda: sign(claims(jti=None)),
    "missing exp": lambda: sign(claims(exp=None)),
    "missing iat": lambda: sign(claims(iat=None)),
    "missing token_type": lambda: sign(claims(token_type=None)),
    "roles not a list": lambda: sign(claims(roles="editor")),
    "numeric subject": lambda: sign(claims(sub=7)),
}


@pytest.mark.parametrize("make", REJECTED.values(), ids=REJECTED.keys())
def test_invalid_tokens_are_rejected(make: Callable[[], str]) -> None:
    with pytest.raises(InvalidToken):
        verify(make())


def test_tampered_payload_is_rejected() -> None:
    header, _, signature = sign(claims(roles=["reader"])).split(".")
    tampered_body = b64(str(claims(roles=["editor"])).replace("'", '"').encode())

    with pytest.raises(InvalidToken):
        verify(f"{header}.{tampered_body}.{signature}")
