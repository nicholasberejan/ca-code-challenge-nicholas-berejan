from django.urls import path

from core.views import health

urlpatterns = [
    path("healthz", health, name="health"),
]
