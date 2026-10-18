from django.urls import path

from content import api, views
from core.views import health

urlpatterns = [
    path("", views.home, name="home"),
    path("brand/", views.brand_list, name="brand-list"),
    path("brand/<slug:slug>/", views.brand_detail, name="brand-detail"),
    path("review/<slug:slug>/", views.review_detail, name="review-detail"),
    path("api/brands/", api.BrandListView.as_view(), name="api-brand-list"),
    path("api/industries/", api.IndustryListView.as_view(), name="api-industry-list"),
    path("healthz", health, name="health"),
]
