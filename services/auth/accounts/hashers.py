"""Transitional support for passwords migrated from WordPress 6.8+.

WordPress stores `$wp` + bcrypt(base64(HMAC-SHA384(password, key="wp-sha384"))).
This mirrors wp_check_password() in wp-includes/pluggable.php (WordPress 6.9):
the submitted password is used as given (not trimmed) and passwords over 4096
bytes never match. Only the `$wp$` format present in the source data is
supported.

Migrated hashes are stored as `wordpress$<WordPress hash>` so Django can
identify this hasher. must_update() is always true, so Django re-hashes the
password with the default hasher on the first successful login
(docs/decisions.md §7). This hasher never creates new hashes.
"""

import base64
import hashlib
import hmac
from typing import Any

import bcrypt
from django.contrib.auth.hashers import BasePasswordHasher, mask_hash

WORDPRESS_PREFIX = "$wp"
HMAC_KEY = b"wp-sha384"
MAX_PASSWORD_BYTES = 4096


class WordPressPasswordHasher(BasePasswordHasher):
    algorithm = "wordpress"

    def encode(self, password: str, salt: str) -> str:
        raise NotImplementedError("WordPress hashes are verified, never created.")

    def _wordpress_hash(self, encoded: str) -> str:
        algorithm, wordpress_hash = encoded.split("$", 1)
        if algorithm != self.algorithm or not wordpress_hash.startswith(
            WORDPRESS_PREFIX + "$"
        ):
            raise ValueError("Not a WordPress $wp$ hash.")
        return wordpress_hash

    def verify(self, password: str, encoded: str) -> bool:
        try:
            wordpress_hash = self._wordpress_hash(encoded)
        except ValueError:
            return False
        secret = password.encode()
        if len(secret) > MAX_PASSWORD_BYTES:
            return False
        prehash = base64.b64encode(hmac.new(HMAC_KEY, secret, hashlib.sha384).digest())
        bcrypt_hash = wordpress_hash.removeprefix(WORDPRESS_PREFIX).encode()
        try:
            return bcrypt.checkpw(prehash, bcrypt_hash)
        except ValueError:
            return False

    def decode(self, encoded: str) -> dict[str, Any]:
        return {"algorithm": self.algorithm, "hash": self._wordpress_hash(encoded)}

    def safe_summary(self, encoded: str) -> dict[str, str]:
        return {
            "algorithm": self.algorithm,
            "hash": mask_hash(self.decode(encoded)["hash"]),
        }

    def must_update(self, encoded: str) -> bool:
        return True

    def harden_runtime(self, password: str, encoded: str) -> None:
        # bcrypt's cost is fixed by the stored hash; nothing to equalise.
        pass


def encode_wordpress_hash(wordpress_hash: str) -> str:
    """The stored form of a migrated `$wp$` hash."""
    return f"{WordPressPasswordHasher.algorithm}${wordpress_hash}"
