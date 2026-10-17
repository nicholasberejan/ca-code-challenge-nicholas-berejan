from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def health(request: HttpRequest) -> JsonResponse:
    """Liveness check. Deliberately touches no database or other service."""
    return JsonResponse({"status": "ok"})
