"""Public server-rendered pages. None of them depends on the auth service."""

from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from content.models import Brand, Review
from content.queries import rounded_average, with_review_stats

RECENT_REVIEWS = 6


def _newest_first(reviews: QuerySet[Review]) -> QuerySet[Review]:
    return reviews.select_related("reviewer").order_by("-published_at", "wp_post_id")


def home(request: HttpRequest) -> HttpResponse:
    recent = _newest_first(Review.objects.select_related("brand"))[:RECENT_REVIEWS]
    return render(request, "content/home.html", {"recent_reviews": recent})


def brand_list(request: HttpRequest) -> HttpResponse:
    # Host page only: <BrandList /> mounts here and loads data from the API.
    return render(request, "content/brand_list.html")


def brand_detail(request: HttpRequest, slug: str) -> HttpResponse:
    brand = get_object_or_404(
        with_review_stats(Brand.objects.all()).prefetch_related("industries"),
        slug=slug,
    )
    industries = sorted(brand.industries.all(), key=lambda i: (i.name, i.slug))
    reviews = _newest_first(brand.reviews.all())
    return render(
        request,
        "content/brand_detail.html",
        {
            "brand": brand,
            "industries": industries,
            "reviews": reviews,
            # The API's two-decimal average; the stars tag shows it to one
            # decimal, rounding half up like the React cards.
            "display_rating": rounded_average(brand.rating_sum, brand.review_count),
        },
    )


def review_detail(request: HttpRequest, slug: str) -> HttpResponse:
    review = get_object_or_404(
        Review.objects.select_related("brand", "reviewer"), slug=slug
    )
    return render(request, "content/review_detail.html", {"review": review})
