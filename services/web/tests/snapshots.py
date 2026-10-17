"""Builders for in-memory WordPress snapshots used by importer tests.

Tests never modify the real WordPress database; they describe the source
state they need with these builders instead.
"""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from content.wordpress.source import Snapshot, SourceBrand, SourceIndustry, SourceReview

PUBLISHED = datetime(2026, 5, 19, 20, 29, 2, tzinfo=UTC)

BRAND_CONTENT = (
    "<p>Acme Insurance is a long-running general-lines insurer offering auto, "
    "home, and umbrella coverage across 38 US states. The company was founded "
    "in Hartford.</p><p>Second paragraph.</p>"
)


def industry(
    term_id: int = 2, slug: str = "insurance", name: str = "Insurance"
) -> SourceIndustry:
    return SourceIndustry(term_id=term_id, slug=slug, name=name)


def brand(
    post_id: int = 7,
    slug: str = "acme-insurance",
    *,
    title: str = "Acme Insurance Co.",
    content: str = BRAND_CONTENT,
    excerpt: str = "",
    industries: tuple[int, ...] = (2,),
    meta: dict[str, str] | None = None,
) -> SourceBrand:
    default_meta = {
        "website_url": "https://acme-insurance.example.com",
        "_website_url": "field_brand_website_url",
        "founded_year": "1985",
        "_founded_year": "field_brand_founded_year",
        "headquarters": "Hartford, CT",
        "_headquarters": "field_brand_headquarters",
        "average_rating": "4.2",
        "_average_rating": "field_brand_average_rating",
        "_yoast_wpseo_title": "Acme Insurance Reviews",
        "_yoast_wpseo_metadesc": "Read 12 independent customer reviews.",
    }
    return SourceBrand(
        post_id=post_id,
        slug=slug,
        title=title,
        content=content,
        excerpt=excerpt,
        published_at=PUBLISHED,
        industry_term_ids=frozenset(industries),
        meta=default_meta if meta is None else meta,
    )


def review(
    post_id: int = 12,
    slug: str | None = None,
    *,
    brand_id: int | str = 7,
    author_id: int = 2,
    author: str | None = "Sarah K.",
    rating: str = "5",
    location: str = "Denver, CO",
    reviewer_name: str | None = None,
    content: str = "<p>Filed the claim online in about 10 minutes.</p>",
    extra_meta: dict[str, str] | None = None,
) -> SourceReview:
    meta = {
        "rating": rating,
        "_rating": "field_review_rating",
        "reviewer_name": author if reviewer_name is None else reviewer_name,
        "_reviewer_name": "field_review_reviewer_name",
        "reviewer_location": location,
        "_reviewer_location": "field_review_reviewer_location",
        "brand": str(brand_id),
        "_brand": "field_review_brand",
        **(extra_meta or {}),
    }
    return SourceReview(
        post_id=post_id,
        slug=slug or f"review-{post_id}",
        title=f"Review {post_id}",
        content=content,
        published_at=PUBLISHED,
        author_id=author_id,
        author_display_name=author,
        meta=meta,
    )


def snapshot(
    industries: list[SourceIndustry] | None = None,
    brands: list[SourceBrand] | None = None,
    reviews: list[SourceReview] | None = None,
) -> Snapshot:
    return Snapshot(
        industries=[industry()] if industries is None else industries,
        brands=[brand()] if brands is None else brands,
        reviews=[review()] if reviews is None else reviews,
    )


def changed(item: Any, **changes: Any) -> Any:
    return replace(item, **changes)
