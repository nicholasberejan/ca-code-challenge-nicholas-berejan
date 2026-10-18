"""Create content rows directly for page and API tests."""

import itertools
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from content.models import Brand, Industry, Review, Reviewer

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_ids = itertools.count(1000)


def make_industry(slug: str, name: str | None = None) -> Industry:
    return Industry.objects.create(
        wp_term_id=next(_ids), slug=slug, name=name or slug.title()
    )


def make_reviewer(name: str = "Sarah K.") -> Reviewer:
    return Reviewer.objects.create(wp_user_id=next(_ids), display_name=name)


def make_review(
    brand: Brand,
    rating: int,
    *,
    published_at: datetime = T0,
    wp_post_id: int | None = None,
    reviewer: Reviewer | None = None,
    title: str | None = None,
    content: str = "<p>Review body.</p>",
    location: str = "Denver, CO",
) -> Review:
    post_id = wp_post_id or next(_ids)
    return Review.objects.create(
        wp_post_id=post_id,
        slug=f"review-{post_id}",
        title=title or f"Review {post_id}",
        content=content,
        rating=rating,
        reviewer_location=location,
        published_at=published_at,
        brand=brand,
        reviewer=reviewer or make_reviewer(),
    )


def make_brand(
    slug: str,
    *,
    industries: Iterable[Industry] = (),
    ratings: Iterable[int] = (),
    **fields: object,
) -> Brand:
    """A brand with one review per rating, each a day newer than the last."""
    defaults: dict[str, object] = {
        "name": slug.replace("-", " ").title(),
        "content": "<p>About the brand.</p>",
        "short_description": f"Short description of {slug}.",
        "published_at": T0,
    }
    brand = Brand.objects.create(
        wp_post_id=next(_ids), slug=slug, **(defaults | fields)
    )
    brand.industries.set(list(industries))
    reviewer = make_reviewer()
    for day, rating in enumerate(ratings):
        make_review(
            brand, rating, published_at=T0 + timedelta(days=day), reviewer=reviewer
        )
    return brand
