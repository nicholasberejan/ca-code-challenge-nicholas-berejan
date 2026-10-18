"""The API's single error shape (docs/decisions.md §4):

    {"errors": {"<param>": ["message", ...]}}

Errors tied to a request parameter or field use its name as the key; errors
that are not (401, 403, 405, 406, ...) use the key "detail".
"""

from typing import Any

from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

NON_FIELD_KEYS = {"non_field_errors", "detail"}


def error_response(errors: dict[str, list[str]], status: int = 400) -> Response:
    return Response({"errors": errors}, status=status)


def _messages(value: Any) -> list[str]:
    """Flatten DRF's nested error details (lists, dicts keyed by list index or
    nested field) into a flat list of messages."""
    if isinstance(value, dict):
        return [m for item in value.values() for m in _messages(item)]
    if isinstance(value, list | tuple):
        return [m for item in value for m in _messages(item)]
    return [str(value)]


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """DRF's handler, with every error body rewritten into the API's shape.

    Exceptions DRF does not handle return None and become ordinary 500s.
    """
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, ValidationError) and isinstance(response.data, dict):
        errors: dict[str, list[str]] = {}
        for key, value in response.data.items():
            name = "detail" if key in NON_FIELD_KEYS else key
            errors.setdefault(name, []).extend(_messages(value))
    else:
        errors = {"detail": _messages(response.data)}

    response.data = {"errors": errors}
    return response
