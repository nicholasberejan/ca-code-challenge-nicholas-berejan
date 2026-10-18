"""import_wordpress_users: create-only migration of WordPress accounts."""

import pytest
from django.contrib.auth.models import Group
from django.db import connection
from django.test.utils import CaptureQueriesContext
from shared_auth.contract import KNOWN_ROLES

from accounts.hashers import encode_wordpress_hash
from accounts.models import User
from accounts.roles import roles_of, set_role
from accounts.wordpress import (
    SourceUser,
    UserImportError,
    format_report,
    import_users,
    parse_capabilities,
)

pytestmark = pytest.mark.django_db

WP_HASH = "$wp$2y$10$" + "a" * 53


def source(
    wp_id: int = 2, login: str = "sarah_k", roles=("subscriber",), **kw
) -> SourceUser:
    return SourceUser(
        wp_user_id=wp_id,
        login=login,
        email=kw.get("email", f"{login}@example.com"),
        password_hash=kw.get("password_hash", WP_HASH),
        wordpress_roles=frozenset(roles),
    )


def test_roles_exist_as_groups_after_migration():
    assert set(Group.objects.values_list("name", flat=True)) >= KNOWN_ROLES


def test_capabilities_are_parsed_from_php_serialization():
    assert parse_capabilities('a:1:{s:13:"administrator";b:1;}') == {"administrator"}
    assert parse_capabilities('a:2:{s:6:"editor";b:1;s:6:"author";b:0;}') == {"editor"}
    assert parse_capabilities("not serialized") == frozenset()
    assert parse_capabilities(None) == frozenset()


@pytest.mark.parametrize(
    ("wordpress_roles", "role", "admin"),
    [
        (("administrator",), "editor", True),
        (("subscriber",), "reader", False),
        (("editor",), "reader", False),  # a WordPress role we do not map
        (("author", "contributor"), "reader", False),
        ((), "reader", False),
    ],
)
def test_wordpress_roles_are_mapped(wordpress_roles, role, admin):
    import_users([source(roles=wordpress_roles)])

    user = User.objects.get()
    assert roles_of(user) == [role]
    assert (user.is_staff, user.is_superuser) == (admin, admin)


def test_accounts_are_created_from_wordpress_fields():
    report = import_users([source(wp_id=5, login="david_l", email="david@example.com")])

    user = User.objects.get()
    assert (user.wp_user_id, user.username, user.email) == (
        5,
        "david_l",
        "david@example.com",
    )
    assert user.password == encode_wordpress_hash(WP_HASH)
    assert user.is_active
    assert report.created == ["david_l"]


def test_second_import_creates_and_modifies_nothing():
    users = [source(1, "admin", ("administrator",)), source(2, "sarah_k")]
    import_users(users)
    before = list(User.objects.order_by("pk").values())

    with CaptureQueriesContext(connection) as queries:
        report = import_users(users)

    assert (report.created, report.unchanged) == ([], 2)
    assert not report.changed
    writes = [
        q["sql"]
        for q in queries.captured_queries
        if q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
    ]
    assert writes == []
    assert list(User.objects.order_by("pk").values()) == before


def test_reimport_preserves_a_changed_role():
    import_users([source(1, "admin", ("administrator",))])
    set_role(User.objects.get(), "reader")

    import_users([source(1, "admin", ("administrator",))])

    assert roles_of(User.objects.get()) == ["reader"]


def test_reimport_preserves_a_deactivation():
    import_users([source()])
    User.objects.update(is_active=False)

    import_users([source()])

    assert not User.objects.get().is_active


def test_reimport_preserves_an_upgraded_password():
    import_users([source()])
    user = User.objects.get()
    user.set_password("a-new-native-password")
    user.save()
    native = user.password

    import_users([source(password_hash="$wp$2y$10$" + "b" * 53)])

    assert User.objects.get().password == native


def test_reimport_preserves_account_changes_made_after_cutover():
    import_users([source(email="old@example.com")])
    User.objects.update(username="sarah", email="new@example.com")

    import_users([source(email="old@example.com")])

    user = User.objects.get()
    assert (user.username, user.email) == ("sarah", "new@example.com")


def test_users_missing_from_wordpress_are_reported_not_deleted():
    import_users([source(1, "admin", ("administrator",)), source(2, "sarah_k")])

    report = import_users([source(1, "admin", ("administrator",))])

    assert report.missing == [(2, "sarah_k")]
    assert User.objects.filter(username="sarah_k").exists()
    assert "2 sarah_k" in format_report(report)


def test_username_taken_by_a_non_imported_account_aborts():
    User.objects.create_user(username="sarah_k", password="x")

    with pytest.raises(UserImportError, match="sarah_k"):
        import_users([source(1, "admin", ("administrator",)), source(2, "sarah_k")])

    assert not User.objects.filter(username="admin").exists()


def test_unsupported_password_formats_get_an_unusable_password():
    report = import_users([source(password_hash="$P$Bphpasshashxxxxxxxxxxxxxxxxxx")])

    assert not User.objects.get().has_usable_password()
    assert report.unsupported_passwords == ["sarah_k"]


def test_seed_users_import_with_their_roles(wordpress_users):
    report = import_users(wordpress_users.values())

    assert len(report.created) == 9
    admin = User.objects.get(username="admin")
    assert roles_of(admin) == ["editor"]
    assert admin.is_staff and admin.is_superuser
    readers = User.objects.exclude(username="admin")
    assert all(roles_of(u) == ["reader"] for u in readers)
    assert not readers.filter(is_staff=True).exists()
    assert report.unsupported_passwords == []


def test_imported_administrator_can_use_the_admin_and_readers_cannot(
    client, wordpress_users
):
    import_users(wordpress_users.values())

    client.force_login(User.objects.get(username="admin"))
    assert client.get("/admin/accounts/user/").status_code == 200

    client.force_login(User.objects.get(username="sarah_k"))
    assert client.get("/admin/accounts/user/").status_code == 302  # to login


def test_imported_administrator_signs_in_to_the_admin_with_the_wordpress_password(
    client, wordpress_users
):
    import_users(wordpress_users.values())

    response = client.post(
        "/admin/login/?next=/admin/",
        {"username": "admin", "password": "admin", "next": "/admin/"},
    )

    assert response.status_code == 302
    assert response["Location"] == "/admin/"
    assert client.get("/admin/accounts/user/").status_code == 200
    # Signing in upgraded the migrated WordPress hash.
    assert User.objects.get(username="admin").password.startswith("pbkdf2_sha256$")


def test_reader_cannot_sign_in_to_the_admin(client, wordpress_users):
    import_users(wordpress_users.values())

    response = client.post(
        "/admin/login/", {"username": "sarah_k", "password": "changeme"}
    )

    # The password is right (the hash was upgraded); the account is not staff.
    assert response.status_code == 200
    assert "staff account" in response.content.decode()
    assert User.objects.get(username="sarah_k").password.startswith("pbkdf2_sha256$")
    assert client.get("/admin/accounts/user/").status_code == 302


def test_operator_changes_a_role_and_deactivates_through_the_admin(client):
    operator = User.objects.create_superuser("op", "op@example.com", "pw")
    import_users([source(1, "admin", ("administrator",))])
    target = User.objects.get(username="admin")
    client.force_login(operator)
    reader = Group.objects.get(name="reader")

    response = client.post(
        f"/admin/accounts/user/{target.pk}/change/",
        {
            "username": target.username,
            "email": target.email,
            "first_name": "",
            "last_name": "",
            "is_active": "",  # unchecked: deactivate
            "is_staff": "",
            "is_superuser": "",
            "groups": [reader.pk],
            "user_permissions": [],
            "last_login_0": "",
            "last_login_1": "",
            "date_joined_0": target.date_joined.strftime("%Y-%m-%d"),
            "date_joined_1": target.date_joined.strftime("%H:%M:%S"),
        },
    )

    assert response.status_code == 302, response.content.decode()[:2000]
    target.refresh_from_db()
    assert roles_of(target) == ["reader"]
    assert not target.is_active
