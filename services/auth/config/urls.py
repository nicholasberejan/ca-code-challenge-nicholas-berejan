from django.urls import path

from accounts.views import health

urlpatterns = [
    path("healthz", health, name="health"),
]
