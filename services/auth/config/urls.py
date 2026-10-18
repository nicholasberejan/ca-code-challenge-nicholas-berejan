from django.contrib import admin
from django.urls import path

from accounts.api import LoginView, LogoutView, RefreshView
from accounts.views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/token/", LoginView.as_view(), name="token-login"),
    path("api/token/refresh/", RefreshView.as_view(), name="token-refresh"),
    path("api/token/logout/", LogoutView.as_view(), name="token-logout"),
    path("healthz", health, name="health"),
]
