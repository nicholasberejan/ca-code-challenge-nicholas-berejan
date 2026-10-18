"""Import a WordPress snapshot into the content models (docs/decisions.md §3).

- Rows are matched by WordPress ID, never by slug.
- WordPress-owned fields are overwritten when they differ; unchanged rows are
  not written, so a re-run against unchanged source reports no updates.
- `Brand.short_description` is Django-owned: set on creation only.
- HTML is sanitized before it is stored.
- Entities missing from the source are reported; they are deleted only with
  `prune=True`.
"""

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from django.db import models, transaction

from content.models import Brand, Industry, Review, Reviewer
from content.sanitize import html_to_text, sanitize_html, summarize
from content.wordpress.source import Snapshot, SourceBrand, SourceReview

# Postmeta strategy (docs/decisions.md §2). Every key is either mapped to a
# field or deliberately dropped; anything else is reported.
BRAND_MAPPED_META = frozenset(
    {"website_url", "founded_year", "headquarters", "average_rating"}
)
BRAND_DROPPED_META = frozenset(
    {
        # ACF field-key references (ACF plumbing).
        "_website_url",
        "_founded_year",
        "_headquarters",
        "_average_rating",
        # Yoast SEO copy: dropped, pages generate <title>/description.
        "_yoast_wpseo_title",
        "_yoast_wpseo_metadesc",
    }
)
REVIEW_MAPPED_META = frozenset({"rating", "reviewer_location", "brand"})
REVIEW_DROPPED_META = frozenset(
    {
        "_rating",
        "_reviewer_location",
        "_brand",
        "_reviewer_name",
        # Compared with the author's display name (mismatches reported), then
        # dropped: the byline comes from Reviewer.display_name.
        "reviewer_name",
    }
)


class SourceDataError(Exception):
    """WordPress data the importer cannot import safely; the import aborts."""


@dataclass
class EntityResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0
    # (WordPress ID, slug or name) of rows in Django but not in the source.
    missing: list[tuple[int, str]] = field(default_factory=list)


@dataclass(frozen=True)
class SkippedReview:
    post_id: int
    slug: str
    brand_reference: str


@dataclass(frozen=True)
class NameMismatch:
    post_id: int
    reviewer_name: str
    display_name: str


@dataclass
class ImportReport:
    industries: EntityResult = field(default_factory=EntityResult)
    brands: EntityResult = field(default_factory=EntityResult)
    reviewers: EntityResult = field(default_factory=EntityResult)
    reviews: EntityResult = field(default_factory=EntityResult)
    skipped_reviews: list[SkippedReview] = field(default_factory=list)
    reviewer_name_mismatches: list[NameMismatch] = field(default_factory=list)
    # (brand post ID, value) of website URLs not stored because they are not
    # http(s) URLs with a host.
    rejected_urls: list[tuple[int, str]] = field(default_factory=list)
    # (post type, meta key) -> number of posts carrying it.
    unknown_meta: dict[tuple[str, str], int] = field(default_factory=dict)
    pruned: bool = False

    def entities(self) -> dict[str, EntityResult]:
        return {
            "industries": self.industries,
            "brands": self.brands,
            "reviewers": self.reviewers,
            "reviews": self.reviews,
        }

    @property
    def changed(self) -> bool:
        return any(
            r.created or r.updated or r.deleted for r in self.entities().values()
        )


def import_snapshot(snapshot: Snapshot, *, prune: bool = False) -> ImportReport:
    """Import everything in one transaction on the main database."""
    report = ImportReport(pruned=prune)
    with transaction.atomic():
        industries = _import_industries(snapshot, report.industries)
        brands = _import_brands(snapshot, industries, report)
        _import_reviews(snapshot, brands, report)
        report.unknown_meta = _unknown_meta(snapshot)
        if prune:
            _prune(report)
        else:
            _check_slug_collisions(snapshot, report)
    return report


def _apply(instance: models.Model, values: dict[str, Any]) -> list[str]:
    """Set the fields whose values differ; return their names."""
    changed = [
        name for name, value in values.items() if getattr(instance, name) != value
    ]
    for name in changed:
        setattr(instance, name, values[name])
    return changed


def _record(result: EntityResult, created: bool, changed: bool) -> None:
    if created:
        result.created += 1
    elif changed:
        result.updated += 1
    else:
        result.unchanged += 1


# --- Industries --------------------------------------------------------------


def _import_industries(snapshot: Snapshot, result: EntityResult) -> dict[int, Industry]:
    existing = {i.wp_term_id: i for i in Industry.objects.all()}
    imported: dict[int, Industry] = {}
    for src in sorted(snapshot.industries, key=lambda s: s.term_id):
        values = {"slug": src.slug, "name": src.name}
        industry = existing.get(src.term_id)
        if industry is None:
            industry = Industry.objects.create(wp_term_id=src.term_id, **values)
            _record(result, created=True, changed=False)
        else:
            changed = _apply(industry, values)
            if changed:
                industry.save(update_fields=changed)
            _record(result, created=False, changed=bool(changed))
        imported[src.term_id] = industry
    result.missing = sorted(
        (term_id, i.slug) for term_id, i in existing.items() if term_id not in imported
    )
    return imported


# --- Brands ------------------------------------------------------------------


def _brand_values(src: SourceBrand) -> dict[str, Any]:
    meta = src.meta
    return {
        "slug": src.slug,
        "name": src.title,
        "content": sanitize_html(src.content),
        "website_url": _web_url(meta.get("website_url", "")),
        "founded_year": _optional_int(meta.get("founded_year"), src.post_id),
        "headquarters": meta.get("headquarters", "").strip(),
        "legacy_average_rating": _optional_decimal(
            meta.get("average_rating"), src.post_id
        ),
        "published_at": src.published_at,
    }


def _seed_short_description(src: SourceBrand) -> str:
    excerpt = html_to_text(src.excerpt)
    return excerpt if excerpt else summarize(src.content)


def _import_brands(
    snapshot: Snapshot, industries: dict[int, Industry], report: ImportReport
) -> dict[int, Brand]:
    result = report.brands
    existing = {b.wp_post_id: b for b in Brand.objects.prefetch_related("industries")}
    imported: dict[int, Brand] = {}
    for src in sorted(snapshot.brands, key=lambda s: s.post_id):
        wanted_industries = {industries[t].pk for t in src.industry_term_ids}
        values = _brand_values(src)
        source_url = src.meta.get("website_url", "").strip()
        if source_url and not values["website_url"]:
            report.rejected_urls.append((src.post_id, source_url))
        brand = existing.get(src.post_id)
        if brand is None:
            brand = Brand.objects.create(
                wp_post_id=src.post_id,
                short_description=_seed_short_description(src),
                **values,
            )
            brand.industries.set(wanted_industries)
            _record(result, created=True, changed=False)
        else:
            changed = _apply(brand, values)
            if changed:
                brand.save(update_fields=changed)
            current_industries = {i.pk for i in brand.industries.all()}
            if current_industries != wanted_industries:
                brand.industries.set(wanted_industries)
            _record(
                result,
                created=False,
                changed=bool(changed) or current_industries != wanted_industries,
            )
        imported[src.post_id] = brand
    result.missing = sorted(
        (post_id, b.slug) for post_id, b in existing.items() if post_id not in imported
    )
    return imported


# --- Reviewers and reviews ---------------------------------------------------


def _import_reviews(
    snapshot: Snapshot, brands: dict[int, Brand], report: ImportReport
) -> None:
    reviewers = {r.wp_user_id: r for r in Reviewer.objects.all()}
    existing = {r.wp_post_id: r for r in Review.objects.all()}
    seen_reviewers: set[int] = set()

    for src in sorted(snapshot.reviews, key=lambda s: s.post_id):
        brand_reference = src.meta.get("brand", "").strip()
        brand = brands.get(_brand_post_id(brand_reference))
        if brand is None:
            report.skipped_reviews.append(
                SkippedReview(src.post_id, src.slug, brand_reference)
            )
            continue

        reviewer = _import_reviewer(src, reviewers, seen_reviewers, report.reviewers)

        reviewer_name = src.meta.get("reviewer_name")
        if reviewer_name is not None and reviewer_name.strip() != reviewer.display_name:
            report.reviewer_name_mismatches.append(
                NameMismatch(src.post_id, reviewer_name, reviewer.display_name)
            )

        values = {
            "slug": src.slug,
            "title": src.title,
            "content": sanitize_html(src.content),
            "rating": _rating(src.meta.get("rating"), src.post_id),
            "reviewer_location": src.meta.get("reviewer_location", "").strip(),
            "published_at": src.published_at,
            "brand_id": brand.pk,
            "reviewer_id": reviewer.pk,
        }
        review = existing.get(src.post_id)
        if review is None:
            Review.objects.create(wp_post_id=src.post_id, **values)
            _record(report.reviews, created=True, changed=False)
        else:
            changed = _apply(review, values)
            if changed:
                review.save(update_fields=changed)
            _record(report.reviews, created=False, changed=bool(changed))

    # Missing = in Django but not imported this run: deleted from WordPress, or
    # skipped because its brand is no longer imported. Like other missing rows,
    # a skipped review is kept as it was (on its previous brand) and reported;
    # --prune deletes it.
    skipped = {s.post_id for s in report.skipped_reviews}
    imported_ids = {src.post_id for src in snapshot.reviews} - skipped
    report.reviews.missing = sorted(
        (post_id, r.slug)
        for post_id, r in existing.items()
        if post_id not in imported_ids
    )
    # Reviewers who author no imported review: with prune, they are left with
    # no reviews and deleted.
    report.reviewers.missing = sorted(
        (user_id, r.display_name)
        for user_id, r in reviewers.items()
        if user_id not in seen_reviewers
    )


def _import_reviewer(
    src: SourceReview,
    reviewers: dict[int, Reviewer],
    seen: set[int],
    result: EntityResult,
) -> Reviewer:
    if src.author_display_name is None:
        raise SourceDataError(
            f"review {src.post_id}: author {src.author_id} does not exist in wp_users"
        )
    reviewer = reviewers.get(src.author_id)
    first_time = src.author_id not in seen
    seen.add(src.author_id)
    if reviewer is None:
        reviewer = Reviewer.objects.create(
            wp_user_id=src.author_id, display_name=src.author_display_name
        )
        reviewers[src.author_id] = reviewer
        _record(result, created=True, changed=False)
    elif first_time:
        changed = _apply(reviewer, {"display_name": src.author_display_name})
        if changed:
            reviewer.save(update_fields=changed)
        _record(result, created=False, changed=bool(changed))
    return reviewer


# --- Postmeta reporting ------------------------------------------------------


def _unknown_meta(snapshot: Snapshot) -> dict[tuple[str, str], int]:
    counts: Counter[tuple[str, str]] = Counter()
    for brand in snapshot.brands:
        for key in brand.meta.keys() - BRAND_MAPPED_META - BRAND_DROPPED_META:
            counts["brand", key] += 1
    for review in snapshot.reviews:
        for key in review.meta.keys() - REVIEW_MAPPED_META - REVIEW_DROPPED_META:
            counts["review", key] += 1
    return dict(sorted(counts.items()))


# --- Slug collisions ---------------------------------------------------------


def _check_slug_collisions(snapshot: Snapshot, report: ImportReport) -> None:
    """Without --prune, a row missing from WordPress keeps its slug. If WordPress
    has given that slug to a different post, stop with a clear error instead of
    failing on the unique constraint at commit."""
    skipped = {s.post_id for s in report.skipped_reviews}
    imported_slugs = {
        "industry": {s.slug: s.term_id for s in snapshot.industries},
        "brand": {s.slug: s.post_id for s in snapshot.brands},
        "review": {
            s.slug: s.post_id for s in snapshot.reviews if s.post_id not in skipped
        },
    }
    missing = {
        "industry": report.industries.missing,
        "brand": report.brands.missing,
        "review": report.reviews.missing,
    }
    for entity, rows in missing.items():
        for old_id, slug in rows:
            new_id = imported_slugs[entity].get(slug)
            if new_id is not None:
                raise SourceDataError(
                    f"{entity} slug {slug!r} now belongs to WordPress ID {new_id}, "
                    f"but is still held by ID {old_id}, which is missing from "
                    "WordPress. Run with --prune to delete the missing row."
                )


# --- Pruning -----------------------------------------------------------------


def _prune(report: ImportReport) -> None:
    """Delete entities missing from the source (docs/decisions.md §3).

    Order matters: reviews and brands go before reviewers, because a reviewer
    cannot be deleted while a review references it (PROTECT).
    """
    _, deleted = Review.objects.filter(
        wp_post_id__in=[post_id for post_id, _ in report.reviews.missing]
    ).delete()
    report.reviews.deleted += deleted.get("content.Review", 0)

    _, deleted = Brand.objects.filter(
        wp_post_id__in=[post_id for post_id, _ in report.brands.missing]
    ).delete()
    report.brands.deleted += deleted.get("content.Brand", 0)
    report.reviews.deleted += deleted.get("content.Review", 0)

    _, deleted = Industry.objects.filter(
        wp_term_id__in=[term_id for term_id, _ in report.industries.missing]
    ).delete()
    report.industries.deleted += deleted.get("content.Industry", 0)

    _, deleted = Reviewer.objects.filter(reviews__isnull=True).delete()
    report.reviewers.deleted += deleted.get("content.Reviewer", 0)


# --- Value parsing -----------------------------------------------------------


def _web_url(value: str) -> str:
    """The brand website is rendered as a link, so only http(s) URLs with a host
    are kept; anything else (e.g. `javascript:`) is stored as empty and
    reported."""
    url = value.strip()
    parts = urlsplit(url)
    return url if parts.scheme.lower() in ("http", "https") and parts.netloc else ""


def _brand_post_id(reference: str) -> int | None:
    return int(reference) if reference.isdigit() else None


def _optional_int(value: str | None, post_id: int) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        return int(value)
    except ValueError:
        raise SourceDataError(
            f"post {post_id}: {value!r} is not a whole number"
        ) from None


def _optional_decimal(value: str | None, post_id: int) -> Decimal | None:
    if value is None or not value.strip():
        return None
    try:
        return Decimal(value.strip())
    except InvalidOperation:
        raise SourceDataError(f"post {post_id}: {value!r} is not a number") from None


def _rating(value: str | None, post_id: int) -> int:
    text = (value or "").strip()
    if not text.isdigit() or not 1 <= int(text) <= 5:
        raise SourceDataError(f"review {post_id}: rating {value!r} is not 1-5")
    return int(text)


# --- Output ------------------------------------------------------------------


def format_report(report: ImportReport) -> str:
    lines = ["WordPress content import"]
    header = f"  {'':<11}{'created':>9}{'updated':>9}{'unchanged':>11}{'missing':>9}"
    if report.pruned:
        header += f"{'deleted':>9}"
    lines.append(header)
    for name, r in report.entities().items():
        row = (
            f"  {name:<11}{r.created:>9}{r.updated:>9}{r.unchanged:>11}"
            f"{len(r.missing):>9}"
        )
        if report.pruned:
            row += f"{r.deleted:>9}"
        lines.append(row)

    missing = [(n, r.missing) for n, r in report.entities().items() if r.missing]
    if missing:
        verb = "deleted (--prune)" if report.pruned else "kept; --prune deletes them"
        lines.append(f"Missing from WordPress ({verb}):")
        for name, rows in missing:
            label = (
                "reviewers with no imported reviews" if name == "reviewers" else name
            )
            lines.append(f"  {label}: " + ", ".join(f"{i} {text}" for i, text in rows))

    if report.skipped_reviews:
        lines.append("Skipped reviews (brand not in the imported source):")
        for s in report.skipped_reviews:
            lines.append(f"  review {s.post_id} {s.slug}: brand {s.brand_reference!r}")

    if report.reviewer_name_mismatches:
        lines.append("Reviewer name mismatches (author display name used):")
        for m in report.reviewer_name_mismatches:
            lines.append(
                f"  review {m.post_id}: reviewer_name {m.reviewer_name!r}, "
                f"author {m.display_name!r}"
            )

    if report.rejected_urls:
        lines.append("Website URLs not stored (not an http(s) URL with a host):")
        for post_id, url in report.rejected_urls:
            lines.append(f"  brand {post_id}: {url!r}")

    if report.unknown_meta:
        lines.append(
            "Unrecognised postmeta keys (not mapped, not dropped; not stored):"
        )
        for (post_type, key), count in report.unknown_meta.items():
            lines.append(f"  {post_type} {key}: {count} post(s)")

    return "\n".join(lines)
