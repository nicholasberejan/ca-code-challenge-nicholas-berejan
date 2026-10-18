from shared_auth.contract import (
    ALGORITHM,
    KNOWN_ROLES,
    REQUIRED_ACCESS_CLAIMS,
    Permission,
    known_roles,
    roles_grant,
)
from shared_auth.principal import Principal


def test_contract_values() -> None:
    assert ALGORITHM == "RS256"
    assert KNOWN_ROLES == {"reader", "editor"}
    assert set(REQUIRED_ACCESS_CLAIMS) == {
        "sub",
        "roles",
        "iss",
        "aud",
        "exp",
        "iat",
        "jti",
        "token_type",
    }


def test_known_roles_filters_and_sorts() -> None:
    assert known_roles(["editor", "staff", "reader", "editor"]) == (
        "editor",
        "reader",
    )


def test_only_editors_may_edit_brands() -> None:
    assert roles_grant(["editor"], Permission.EDIT_BRAND)
    assert roles_grant(["reader", "editor"], Permission.EDIT_BRAND)
    assert not roles_grant(["reader"], Permission.EDIT_BRAND)
    assert not roles_grant([], Permission.EDIT_BRAND)
    assert not roles_grant(["admin"], Permission.EDIT_BRAND)


def test_principal_is_authenticated_and_checks_permissions() -> None:
    editor = Principal(subject="1", roles=("editor",), token_id="t")
    reader = Principal(subject="2", roles=("reader",), token_id="u")

    assert editor.is_authenticated and not editor.is_anonymous
    assert editor.has_permission(Permission.EDIT_BRAND)
    assert not reader.has_permission(Permission.EDIT_BRAND)
