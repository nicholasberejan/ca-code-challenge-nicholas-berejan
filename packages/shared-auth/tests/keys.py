"""Throwaway RSA keys and token builders for tests (never real keys)."""

import base64
import hashlib
import hmac
import json
import time
import uuid
from functools import cache
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "https://auth.test"
AUDIENCE = "web.test"


def key_pair(name: str = "issuer") -> tuple[str, str]:
    """(private PEM, public PEM), generated once per name per test run."""
    return _generate(name)


@cache
def _generate(name: str) -> tuple[str, str]:
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


def claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": "42",
        "roles": ["editor"],
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 300,
        "jti": uuid.uuid4().hex,
        "token_type": "access",
    }
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not None}


def sign(payload: dict[str, Any], *, key: str = "issuer") -> str:
    return jwt.encode(payload, key_pair(key)[0], algorithm="RS256")


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def forge_hs256_with_public_key(payload: dict[str, Any]) -> str:
    """The classic algorithm-confusion attack: HS256 keyed with the public key."""
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64(json.dumps(payload).encode())
    secret = key_pair()[1].encode()
    signature = hmac.new(secret, f"{header}.{body}".encode(), hashlib.sha256)
    return f"{header}.{body}.{b64(signature.digest())}"


def unsigned(payload: dict[str, Any]) -> str:
    header = b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    return f"{header}.{b64(json.dumps(payload).encode())}."
