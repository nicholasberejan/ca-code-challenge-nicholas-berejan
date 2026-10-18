"""Migrated WordPress passwords: verified, then upgraded on first login.

Uses the seed's real hashes, produced by WordPress itself, so the hasher is
checked against the reference implementation rather than against itself.
"""

import pytest
from django.contrib.auth.hashers import check_password, identify_hasher

from accounts.hashers import WordPressPasswordHasher, encode_wordpress_hash
from accounts.models import User
from accounts.wordpress import import_users

pytestmark = pytest.mark.django_db


def login(client, username, password):
    return client.post(
        "/api/token/",
        {"username": username, "password": password},
        content_type="application/json",
    )


@pytest.mark.parametrize(
    ("username", "password"), [("admin", "admin"), ("sarah_k", "changeme")]
)
def test_correct_wordpress_password_verifies(wordpress_users, username, password):
    encoded = encode_wordpress_hash(wordpress_users[username].password_hash)

    assert check_password(password, encoded)


@pytest.mark.parametrize(
    "password",
    ["wrong", "", "Changeme", "changeme ", " changeme", "changem"],
)
def test_wrong_wordpress_password_is_rejected(wordpress_users, password):
    # WordPress does not trim at check time, so neither do we.
    encoded = encode_wordpress_hash(wordpress_users["sarah_k"].password_hash)

    assert not check_password(password, encoded)


def test_hasher_rejects_hashes_that_are_not_wordpress_wp_hashes():
    hasher = WordPressPasswordHasher()

    assert not hasher.verify("admin", "wordpress$$P$Babcdefghijklmnopqrstuv")
    assert not hasher.verify("admin", "wordpress$garbage")
    assert not hasher.verify("x" * 4097, "wordpress$$wp$2y$10$" + "a" * 53)


def test_hasher_never_creates_wordpress_hashes():
    with pytest.raises(NotImplementedError):
        WordPressPasswordHasher().encode("password", "salt")


def test_first_login_upgrades_the_hash_and_the_password_keeps_working(
    client, wordpress_users
):
    import_users([wordpress_users["sarah_k"]])
    assert identify_hasher(User.objects.get().password).algorithm == "wordpress"

    assert login(client, "sarah_k", "changeme").status_code == 200

    upgraded = User.objects.get().password
    assert upgraded.startswith("pbkdf2_sha256$")
    assert "$wp$" not in upgraded
    assert login(client, "sarah_k", "changeme").status_code == 200
    assert login(client, "sarah_k", "wrong").status_code == 401


def test_wrong_password_does_not_upgrade_the_hash(client, wordpress_users):
    import_users([wordpress_users["sarah_k"]])

    assert login(client, "sarah_k", "wrong").status_code == 401

    assert identify_hasher(User.objects.get().password).algorithm == "wordpress"


def test_reimport_does_not_restore_the_wordpress_hash(client, wordpress_users):
    import_users([wordpress_users["admin"]])
    assert login(client, "admin", "admin").status_code == 200
    upgraded = User.objects.get().password

    import_users([wordpress_users["admin"]])

    assert User.objects.get().password == upgraded
    assert login(client, "admin", "admin").status_code == 200
