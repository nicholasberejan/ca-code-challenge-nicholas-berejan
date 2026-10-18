"""Public, read-only brand listing API (docs/decisions.md §4)."""

from django.core.paginator import EmptyPage, Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.utils.urls import remove_query_param, replace_query_param
from rest_framework.views import APIView
from shared_auth.drf import CanEditBrands, JWTAuthentication

from content.models import Brand, Industry, Review
from content.queries import (
    DEFAULT_ORDERING,
    ORDERINGS,
    brand_listing,
    rounded_average,
    top_reviews,
    with_review_stats,
)
from content.sanitize import snippet
from core.api_errors import error_response

DEFAULT_PAGE_SIZE = 12
MAX_PAGE_SIZE = 50


# --- Query parameters --------------------------------------------------------


class BrandListParameters(serializers.Serializer):
    # Plain strings, validated together below, so errors stay a flat list.
    industry = serializers.ListField(
        child=serializers.CharField(allow_blank=True), required=False
    )
    ordering = serializers.ChoiceField(choices=ORDERINGS, default=DEFAULT_ORDERING)
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(
        min_value=1, max_value=MAX_PAGE_SIZE, default=DEFAULT_PAGE_SIZE
    )

    def validate_industry(self, slugs: list[str]) -> list[str]:
        unique = sorted(set(slugs))
        known = set(
            Industry.objects.filter(slug__in=unique).values_list("slug", flat=True)
        )
        unknown = [slug for slug in unique if slug not in known]
        if unknown:
            raise serializers.ValidationError(
                [f"Unknown industry: {slug!r}." for slug in unknown]
            )
        return unique


def _parameters(request: Request) -> dict[str, object]:
    params = request.query_params
    data: dict[str, object] = {}
    if "industry" in params:
        data["industry"] = params.getlist("industry")
    for name in ("ordering", "page", "page_size"):
        if name in params:
            data[name] = params[name]
    return data


# --- Representation ----------------------------------------------------------


class IndustrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Industry
        fields = ["slug", "name"]


class TopReviewSerializer(serializers.ModelSerializer):
    reviewer_name = serializers.CharField(source="reviewer.display_name")
    snippet = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = ["slug", "title", "rating", "reviewer_name", "snippet"]

    def get_snippet(self, review: Review) -> str:
        return snippet(review.content)


class BrandListSerializer(serializers.ModelSerializer):
    industries = serializers.SerializerMethodField()
    average_rating = serializers.SerializerMethodField()
    review_count = serializers.IntegerField()
    top_review = serializers.SerializerMethodField()

    class Meta:
        model = Brand
        fields = [
            "name",
            "slug",
            "industries",
            "average_rating",
            "review_count",
            "short_description",
            "top_review",
        ]

    def get_industries(self, brand: Brand) -> list[dict[str, str]]:
        industries = sorted(brand.industries.all(), key=lambda i: (i.name, i.slug))
        return IndustrySerializer(industries, many=True).data

    def get_average_rating(self, brand: Brand) -> float | None:
        # A JSON number rounded to two decimals; ordering uses the unrounded
        # database aggregate.
        average = rounded_average(brand.rating_sum, brand.review_count)
        return None if average is None else float(average)

    def get_top_review(self, brand: Brand) -> dict[str, object] | None:
        review = self.context["top_reviews"].get(brand.pk)
        return None if review is None else TopReviewSerializer(review).data


# --- Views -------------------------------------------------------------------


class BrandListView(APIView):
    """GET /api/brands/: filter by industry (repeatable, any-of), order, paginate."""

    def get(self, request: Request) -> Response:
        parameters = BrandListParameters(data=_parameters(request))
        if not parameters.is_valid():
            return error_response(parameters.errors)
        params = parameters.validated_data

        brands = brand_listing(params.get("industry", ()), params["ordering"])
        paginator = Paginator(brands, params["page_size"])
        try:
            page = paginator.page(params["page"])
        except EmptyPage:
            return error_response({"page": ["Page out of range."]}, status=404)

        results = list(page.object_list)
        serializer = BrandListSerializer(
            results, many=True, context={"top_reviews": top_reviews(results)}
        )
        return Response(
            {
                "count": paginator.count,
                "next": self._page_url(request, page.next_page_number())
                if page.has_next()
                else None,
                "previous": self._page_url(request, page.previous_page_number())
                if page.has_previous()
                else None,
                "results": serializer.data,
            }
        )

    @staticmethod
    def _page_url(request: Request, number: int) -> str:
        url = request.build_absolute_uri()
        if number == 1:
            return remove_query_param(url, "page")
        return replace_query_param(url, "page", number)


class IndustryListView(APIView):
    """GET /api/industries/: every industry, for the filter options."""

    def get(self, request: Request) -> Response:
        industries = Industry.objects.order_by("name", "slug")
        return Response(IndustrySerializer(industries, many=True).data)


# --- Protected edit ------------------------------------------------------------

EDITABLE_FIELDS = {"short_description"}
SHORT_DESCRIPTION_MAX_LENGTH = 300


class BrandEditSerializer(serializers.Serializer):
    """The only writable brand field. Plain text: stored as given (trimmed)
    and escaped when rendered; HTML is not interpreted."""

    short_description = serializers.CharField(
        max_length=SHORT_DESCRIPTION_MAX_LENGTH, allow_blank=False, trim_whitespace=True
    )

    def to_internal_value(self, data: object) -> dict[str, str]:
        if not isinstance(data, dict):
            raise serializers.ValidationError({"detail": ["Expected a JSON object."]})
        errors = {
            name: ["This field cannot be changed."]
            for name in sorted(set(data) - EDITABLE_FIELDS)
        }
        value = data.get("short_description")
        if "short_description" in data and not isinstance(value, str):
            errors["short_description"] = ["Must be a string."]
        if errors:
            raise serializers.ValidationError(errors)
        return super().to_internal_value(data)


class BrandDetailView(APIView):
    """PATCH /api/brands/<slug>/: editors change a brand's short description.

    The token is verified locally with the auth service's public key: 401 for
    a missing or invalid token, 403 without the editor role.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [CanEditBrands]

    def patch(self, request: Request, slug: str) -> Response:
        brand = get_object_or_404(Brand, slug=slug)
        edit = BrandEditSerializer(data=request.data)
        edit.is_valid(raise_exception=True)
        with transaction.atomic():
            brand.short_description = edit.validated_data["short_description"]
            brand.save(update_fields=["short_description"])

        # The same representation as a listing row.
        row = (
            with_review_stats(Brand.objects.filter(pk=brand.pk))
            .prefetch_related("industries")
            .get()
        )
        return Response(
            BrandListSerializer(row, context={"top_reviews": top_reviews([row])}).data
        )
