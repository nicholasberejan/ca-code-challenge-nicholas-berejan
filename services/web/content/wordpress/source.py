"""Read published WordPress content into plain data (docs/decisions.md §3).

This module only issues SELECTs. The `wordpress` connection is additionally
opened as a read-only session (see config/settings.py), so a write through it
fails even though the local `wp` database user could write.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from django.db.backends.base.base import BaseDatabaseWrapper


@dataclass(frozen=True)
class SourceIndustry:
    term_id: int
    slug: str
    name: str


@dataclass(frozen=True)
class SourceBrand:
    post_id: int
    slug: str
    title: str
    content: str
    excerpt: str
    published_at: datetime
    industry_term_ids: frozenset[int]
    meta: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceReview:
    post_id: int
    slug: str
    title: str
    content: str
    published_at: datetime
    author_id: int
    # None when the author no longer exists in wp_users.
    author_display_name: str | None
    meta: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Snapshot:
    industries: list[SourceIndustry]
    brands: list[SourceBrand]
    reviews: list[SourceReview]


def _utc(value: datetime) -> datetime:
    # post_date_gmt is stored as a naive UTC datetime.
    return value.replace(tzinfo=UTC)


def read_snapshot(connection: BaseDatabaseWrapper) -> Snapshot:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT t.term_id, t.slug, t.name
            FROM wp_terms t
            JOIN wp_term_taxonomy tt ON tt.term_id = t.term_id
            WHERE tt.taxonomy = 'industry'
            """
        )
        industries = [
            SourceIndustry(term_id=row[0], slug=row[1], name=row[2])
            for row in cursor.fetchall()
        ]

        cursor.execute(
            """
            SELECT p.ID, m.meta_key, m.meta_value
            FROM wp_postmeta m
            JOIN wp_posts p ON p.ID = m.post_id
            WHERE p.post_type IN ('brand', 'review') AND p.post_status = 'publish'
            ORDER BY m.meta_id
            """
        )
        meta: dict[int, dict[str, str]] = defaultdict(dict)
        for post_id, key, value in cursor.fetchall():
            meta[post_id][key] = value if value is not None else ""

        cursor.execute(
            """
            SELECT r.object_id, tt.term_id
            FROM wp_term_relationships r
            JOIN wp_term_taxonomy tt
              ON tt.term_taxonomy_id = r.term_taxonomy_id AND tt.taxonomy = 'industry'
            """
        )
        terms_by_post: dict[int, set[int]] = defaultdict(set)
        for post_id, term_id in cursor.fetchall():
            terms_by_post[post_id].add(term_id)

        cursor.execute(
            """
            SELECT ID, post_name, post_title, post_content, post_excerpt,
                   post_date_gmt
            FROM wp_posts
            WHERE post_type = 'brand' AND post_status = 'publish'
            """
        )
        brands = [
            SourceBrand(
                post_id=row[0],
                slug=row[1],
                title=row[2],
                content=row[3],
                excerpt=row[4],
                published_at=_utc(row[5]),
                industry_term_ids=frozenset(terms_by_post.get(row[0], ())),
                meta=meta.get(row[0], {}),
            )
            for row in cursor.fetchall()
        ]

        cursor.execute(
            """
            SELECT p.ID, p.post_name, p.post_title, p.post_content,
                   p.post_date_gmt, p.post_author, u.display_name
            FROM wp_posts p
            LEFT JOIN wp_users u ON u.ID = p.post_author
            WHERE p.post_type = 'review' AND p.post_status = 'publish'
            """
        )
        reviews = [
            SourceReview(
                post_id=row[0],
                slug=row[1],
                title=row[2],
                content=row[3],
                published_at=_utc(row[4]),
                author_id=row[5],
                author_display_name=row[6],
                meta=meta.get(row[0], {}),
            )
            for row in cursor.fetchall()
        ]

    return Snapshot(industries=industries, brands=brands, reviews=reviews)
