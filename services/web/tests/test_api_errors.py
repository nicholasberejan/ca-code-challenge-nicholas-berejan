"""Every API error uses {"errors": {"<param or detail>": [messages]}}."""

import pytest
from rest_framework import exceptions

from core.api_errors import api_exception_handler

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("path", ["/api/brands/", "/api/industries/"])
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_unsupported_methods_use_the_error_shape(client, path, method):
    response = getattr(client, method)(path)

    assert response.status_code == 405
    assert response.json() == {
        "errors": {"detail": [f'Method "{method.upper()}" not allowed.']}
    }


def test_unacceptable_accept_header_uses_the_error_shape(client):
    response = client.get("/api/brands/", HTTP_ACCEPT="application/xml")

    assert response.status_code == 406
    assert response.json() == {
        "errors": {"detail": ["Could not satisfy the request Accept header."]}
    }


def test_parameter_errors_keep_their_shape(client):
    response = client.get("/api/brands/?ordering=x")

    assert response.json() == {"errors": {"ordering": ['"x" is not a valid choice.']}}


@pytest.mark.parametrize(
    ("exc", "status", "errors"),
    [
        (
            exceptions.NotAuthenticated(),
            401,
            {"detail": ["Authentication credentials were not provided."]},
        ),
        (
            exceptions.PermissionDenied(),
            403,
            {"detail": ["You do not have permission to perform this action."]},
        ),
        (
            exceptions.ValidationError({"short_description": ["Too long."]}),
            400,
            {"short_description": ["Too long."]},
        ),
        (
            exceptions.ValidationError({"non_field_errors": ["Bad combination."]}),
            400,
            {"detail": ["Bad combination."]},
        ),
        (
            exceptions.ValidationError(["Top-level problem."]),
            400,
            {"detail": ["Top-level problem."]},
        ),
        (
            exceptions.ValidationError(
                {"tags": {0: ["Bad item."], 2: ["Worse item."]}}
            ),
            400,
            {"tags": ["Bad item.", "Worse item."]},
        ),
    ],
)
def test_handler_rewrites_drf_errors_into_the_shape(exc, status, errors):
    response = api_exception_handler(exc, {})

    assert response.status_code == status
    assert response.data == {"errors": errors}


def test_exceptions_drf_does_not_handle_are_left_alone():
    assert api_exception_handler(ValueError("boom"), {}) is None
