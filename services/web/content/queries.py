"""Brand read queries: derived ratings, industry filtering, ordering and the
representative ("top") review (docs/decisions.md §4).

The current average rating is always derived from Review rows;
`Brand.legacy_average_rating` is never used here.
"""

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Avg, Count, F, FloatField, QuerySet, Sum

from content.models import Brand, Review

ORDERINGS = ("average_rating", "-average_rating", "review_count", "-review_count")
DEFAULT_ORDERING = "-average_rating"


def with_review_stats(brands: QuerySet[Brand]) -> QuerySet[Brand]:
    """Annotate review_count, rating_sum and the unrounded average_rating
    (NULL for a brand without reviews)."""
    return brands.annotate(
        review_count=Count("reviews"),
        rating_sum=Sum("reviews__rating"),
        average_rating=Avg("reviews__rating", output_field=FloatField()),
    )


def brand_listing(
    industry_slugs: Iterable[str] = (), ordering: str = DEFAULT_ORDERING
) -> QuerySet[Brand]:
    """Brands with review statistics, filtered and ordered for the listing.

    Industry filter: brands in ANY of the given industries. Membership is a
    subquery on brand IDs, so the aggregate query never joins industries and a
    brand matching several industries cannot have its reviews counted twice.
    """
    if ordering not in ORDERINGS:
        raise ValueError(f"unsupported ordering {ordering!r}")
    brands = Brand.objects.all()
    slugs = set(industry_slugs)
    if slugs:
        brands = brands.filter(
            pk__in=Brand.objects.filter(industries__slug__in=slugs).values("pk")
        )
    field = ordering.lstrip("-")
    order = (
        F(field).desc(nulls_last=True)
        if ordering.startswith("-")
        else F(field).asc(nulls_last=True)
    )
    return (
        with_review_stats(brands).prefetch_related("industries").order_by(order, "slug")
    )


def rounded_average(rating_sum: int | None, review_count: int) -> Decimal | None:
    """The exact mean of the ratings rounded half-up to two decimals; None
    when there are no reviews."""
    if not review_count or rating_sum is None:
        return None
    return (Decimal(rating_sum) / Decimal(review_count)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def top_reviews(brands: Iterable[Brand]) -> dict[int, Review]:
    """The representative review of each brand (annotated by
    `with_review_stats`), keyed by brand ID. Brands without reviews are absent.

    The review whose rating is closest to the brand's mean wins. Distance is
    compared exactly with integers: |rating * review_count - rating_sum| is
    the distance from the mean multiplied by review_count. Ties: lower rating
    (only reached when equally distant), then most recent, then WordPress ID.
    """
    stats = {b.pk: (b.review_count, b.rating_sum) for b in brands if b.review_count}
    if not stats:
        return {}

    best: dict[int, tuple[tuple[int, int, float, int], int]] = {}
    candidates = Review.objects.filter(brand_id__in=stats).values_list(
        "pk", "brand_id", "rating", "published_at", "wp_post_id"
    )
    for pk, brand_id, rating, published_at, wp_post_id in candidates:
        count, total = stats[brand_id]
        key = (
            abs(rating * count - total),
            rating,
            -published_at.timestamp(),
            wp_post_id,
        )
        if brand_id not in best or key < best[brand_id][0]:
            best[brand_id] = (key, pk)

    winners = Review.objects.select_related("reviewer").in_bulk(
        [pk for _, pk in best.values()]
    )
    return {brand_id: winners[pk] for brand_id, (_, pk) in best.items()}
