"""WordPress content import: identity, ownership, idempotency, reporting, pruning.

The source is described with in-memory snapshots; the importer runs for real
against PostgreSQL.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.db import connection, models
from django.db.models import ProtectedError, QuerySet
from django.test.utils import CaptureQueriesContext

from content.models import Brand, Industry, Review, Reviewer
from content.wordpress.importer import (
    SourceDataError,
    format_report,
    import_snapshot,
)

from .snapshots import brand, changed, industry, review, snapshot

pytestmark = pytest.mark.django_db

TWO_BRANDS = snapshot(
    industries=[
        industry(2, "insurance", "Insurance"),
        industry(3, "telecom", "Telecom"),
    ],
    brands=[brand(7, "acme-insurance"), brand(8, "swiftstream", industries=(3,))],
    reviews=[
        review(12, brand_id=7, author_id=2, author="Sarah K.", location="Denver, CO"),
        review(13, brand_id=7, author_id=3, author="Mike T.", rating="3"),
        review(14, brand_id=8, author_id=2, author="Sarah K.", location="Tucson, AZ"),
    ],
)


def counts(result):
    return (result.created, result.updated, result.unchanged, len(result.missing))


# --- First import ------------------------------------------------------------


def test_first_import_creates_all_entities_with_source_values():
    report = import_snapshot(TWO_BRANDS)

    assert counts(report.industries) == (2, 0, 0, 0)
    assert counts(report.brands) == (2, 0, 0, 0)
    assert counts(report.reviewers) == (2, 0, 0, 0)
    assert counts(report.reviews) == (3, 0, 0, 0)

    acme = Brand.objects.get(wp_post_id=7)
    assert acme.slug == "acme-insurance"
    assert acme.name == "Acme Insurance Co."
    assert acme.website_url == "https://acme-insurance.example.com"
    assert acme.founded_year == 1985
    assert acme.headquarters == "Hartford, CT"
    assert acme.published_at == datetime(2026, 5, 19, 20, 29, 2, tzinfo=UTC)
    assert [i.slug for i in acme.industries.all()] == ["insurance"]

    review_13 = Review.objects.get(wp_post_id=13)
    assert review_13.brand == acme
    assert review_13.rating == 3
    assert review_13.reviewer.wp_user_id == 3


def test_short_description_is_seeded_from_first_22_words_of_content():
    import_snapshot(snapshot())

    assert Brand.objects.get(wp_post_id=7).short_description == (
        "Acme Insurance is a long-running general-lines insurer offering auto, home, "
        "and umbrella coverage across 38 US states. The company was founded in…"
    )


def test_short_description_prefers_the_excerpt_when_present():
    import_snapshot(
        snapshot(brands=[brand(excerpt="Trusted &amp; local <b>insurer</b>.")])
    )

    assert (
        Brand.objects.get(wp_post_id=7).short_description == "Trusted & local insurer."
    )


def test_seeded_short_description_may_exceed_the_edit_limit():
    long_excerpt = "word " * 100

    import_snapshot(snapshot(brands=[brand(excerpt=long_excerpt)]))

    assert len(Brand.objects.get(wp_post_id=7).short_description) > 300


def test_only_review_authors_become_reviewers():
    import_snapshot(TWO_BRANDS)

    assert sorted(Reviewer.objects.values_list("wp_user_id", flat=True)) == [2, 3]


# --- Ratings -----------------------------------------------------------------


def test_legacy_average_rating_is_kept_but_is_not_a_current_average_field():
    import_snapshot(TWO_BRANDS)

    acme = Brand.objects.get(wp_post_id=7)
    assert acme.legacy_average_rating == Decimal("4.2")
    field_names = {f.name for f in Brand._meta.get_fields()}
    assert "average_rating" not in field_names
    assert "legacy_average_rating" in field_names


def test_blank_optional_brand_meta_is_imported_as_empty():
    meta = {
        "website_url": "",
        "founded_year": "",
        "headquarters": "",
        "average_rating": "",
    }

    import_snapshot(snapshot(brands=[brand(meta=meta)]))

    acme = Brand.objects.get(wp_post_id=7)
    assert (acme.website_url, acme.founded_year, acme.headquarters) == ("", None, "")
    assert acme.legacy_average_rating is None


@pytest.mark.parametrize("bad_rating", ["", "6", "0", "five"])
def test_invalid_review_rating_aborts_the_import(bad_rating):
    with pytest.raises(SourceDataError, match="rating"):
        import_snapshot(snapshot(reviews=[review(rating=bad_rating)]))

    assert not Brand.objects.exists()


# --- Source identity and slug changes ----------------------------------------


def test_slug_change_updates_the_existing_brand_and_keeps_django_owned_fields():
    import_snapshot(snapshot(brands=[brand(123, "old-slug")], reviews=[]))
    original = Brand.objects.get(wp_post_id=123)
    original.short_description = "Edited by an editor."
    original.save()

    report = import_snapshot(snapshot(brands=[brand(123, "new-slug")], reviews=[]))

    assert Brand.objects.filter(wp_post_id=123).count() == 1
    assert Brand.objects.count() == 1
    renamed = Brand.objects.get(wp_post_id=123)
    assert renamed.pk == original.pk
    assert renamed.slug == "new-slug"
    assert renamed.short_description == "Edited by an editor."
    assert counts(report.brands) == (0, 1, 0, 0)


def test_slug_changes_update_reviews_and_industries_in_place():
    import_snapshot(snapshot())
    review_pk = Review.objects.get().pk
    industry_pk = Industry.objects.get().pk

    import_snapshot(
        snapshot(
            industries=[industry(slug="insurance-new", name="Insurance & Cover")],
            brands=[brand()],
            reviews=[review(slug="renamed-review")],
        )
    )

    assert Review.objects.get().pk == review_pk
    assert Review.objects.get().slug == "renamed-review"
    assert Industry.objects.get().pk == industry_pk
    assert Industry.objects.get().name == "Insurance & Cover"


def test_two_brands_can_swap_slugs_in_one_import():
    import_snapshot(snapshot(brands=[brand(7, "a"), brand(8, "b")], reviews=[]))

    import_snapshot(snapshot(brands=[brand(7, "b"), brand(8, "a")], reviews=[]))

    assert dict(Brand.objects.values_list("wp_post_id", "slug")) == {7: "b", 8: "a"}


# --- Django-owned field ------------------------------------------------------


def test_reimport_never_overwrites_short_description():
    import_snapshot(snapshot())
    Brand.objects.filter(wp_post_id=7).update(short_description="Editor's text.")

    import_snapshot(
        snapshot(
            brands=[
                brand(
                    slug="acme-renamed",
                    excerpt="A brand new excerpt.",
                    content="<p>Completely different content.</p>",
                )
            ]
        )
    )

    acme = Brand.objects.get(wp_post_id=7)
    assert acme.short_description == "Editor's text."
    assert acme.content == "<p>Completely different content.</p>"


def test_source_changes_to_wordpress_owned_fields_are_applied():
    import_snapshot(TWO_BRANDS)

    new_meta = {**brand().meta, "headquarters": "Boston, MA", "average_rating": "3.9"}
    report = import_snapshot(
        snapshot(
            industries=TWO_BRANDS.industries,
            brands=[
                changed(TWO_BRANDS.brands[0], title="Acme Mutual", meta=new_meta),
                TWO_BRANDS.brands[1],
            ],
            reviews=[
                changed(TWO_BRANDS.reviews[0], title="New title"),
                *TWO_BRANDS.reviews[1:],
            ],
        )
    )

    acme = Brand.objects.get(wp_post_id=7)
    assert (acme.name, acme.headquarters) == ("Acme Mutual", "Boston, MA")
    assert acme.legacy_average_rating == Decimal("3.9")
    assert Review.objects.get(wp_post_id=12).title == "New title"
    assert counts(report.brands) == (0, 1, 1, 0)
    assert counts(report.reviews) == (0, 1, 2, 0)


# --- Idempotency -------------------------------------------------------------


def test_second_import_of_unchanged_source_creates_and_updates_nothing():
    import_snapshot(TWO_BRANDS)
    before = {
        model: list(model.objects.order_by("pk").values())
        for model in (Industry, Brand, Reviewer, Review)
    }

    with CaptureQueriesContext(connection) as queries:
        report = import_snapshot(TWO_BRANDS)

    assert not report.changed
    assert counts(report.industries) == (0, 0, 2, 0)
    assert counts(report.brands) == (0, 0, 2, 0)
    assert counts(report.reviewers) == (0, 0, 2, 0)
    assert counts(report.reviews) == (0, 0, 3, 0)
    writes = [
        q["sql"]
        for q in queries.captured_queries
        if q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
    ]
    assert writes == []
    after = {
        model: list(model.objects.order_by("pk").values())
        for model in (Industry, Brand, Reviewer, Review)
    }
    assert after == before


# --- Industries --------------------------------------------------------------


def industries_of(post_id):
    return sorted(
        Brand.objects.get(wp_post_id=post_id).industries.values_list("slug", flat=True)
    )


THREE_INDUSTRIES = [
    industry(2, "insurance"),
    industry(3, "telecom"),
    industry(4, "finance"),
]


def test_brand_industries_are_replaced_to_match_the_source():
    import_snapshot(
        snapshot(industries=THREE_INDUSTRIES, brands=[brand(industries=(2,))])
    )
    assert industries_of(7) == ["insurance"]

    report = import_snapshot(
        snapshot(industries=THREE_INDUSTRIES, brands=[brand(industries=(2, 3, 4))])
    )
    assert industries_of(7) == ["finance", "insurance", "telecom"]
    assert counts(report.brands) == (0, 1, 0, 0)

    report = import_snapshot(
        snapshot(industries=THREE_INDUSTRIES, brands=[brand(industries=(4,))])
    )
    assert industries_of(7) == ["finance"]
    assert counts(report.brands) == (0, 1, 0, 0)


def test_unchanged_industry_set_is_not_an_update():
    source = snapshot(industries=THREE_INDUSTRIES, brands=[brand(industries=(2, 3))])
    import_snapshot(source)

    report = import_snapshot(source)

    assert counts(report.brands) == (0, 0, 1, 0)


def test_brand_may_hold_multiple_industries():
    import_snapshot(
        snapshot(industries=THREE_INDUSTRIES, brands=[brand(industries=(2, 3, 4))])
    )

    assert industries_of(7) == ["finance", "insurance", "telecom"]


# --- Reviewers ---------------------------------------------------------------


def test_reviews_by_one_author_share_one_reviewer():
    import_snapshot(TWO_BRANDS)

    sarah = Reviewer.objects.get(wp_user_id=2)
    assert sorted(sarah.reviews.values_list("wp_post_id", flat=True)) == [12, 14]
    assert Reviewer.objects.count() == 2


def test_location_belongs_to_each_review_not_the_reviewer():
    import_snapshot(TWO_BRANDS)

    sarah = Reviewer.objects.get(wp_user_id=2)
    assert dict(sarah.reviews.values_list("wp_post_id", "reviewer_location")) == {
        12: "Denver, CO",
        14: "Tucson, AZ",
    }
    assert "reviewer_location" not in {f.name for f in Reviewer._meta.get_fields()}


def test_reviewer_display_name_follows_the_author():
    import_snapshot(snapshot())

    report = import_snapshot(snapshot(reviews=[review(author="Sarah Kim")]))

    assert Reviewer.objects.get(wp_user_id=2).display_name == "Sarah Kim"
    assert counts(report.reviewers) == (0, 1, 0, 0)


def test_reviewer_name_mismatch_is_reported_and_the_display_name_is_used():
    report = import_snapshot(snapshot(reviews=[review(reviewer_name="S. Kowalski")]))

    assert Review.objects.get(wp_post_id=12).reviewer.display_name == "Sarah K."
    assert [
        (m.post_id, m.reviewer_name, m.display_name)
        for m in report.reviewer_name_mismatches
    ] == [(12, "S. Kowalski", "Sarah K.")]
    assert "reviewer_name" not in {f.name for f in Review._meta.get_fields()}


def test_review_whose_author_is_missing_aborts_the_import():
    with pytest.raises(SourceDataError, match="does not exist in wp_users"):
        import_snapshot(snapshot(reviews=[review(author=None)]))


def test_reviewer_cannot_be_deleted_while_a_review_references_it():
    import_snapshot(snapshot())

    with pytest.raises(ProtectedError):
        Reviewer.objects.get(wp_user_id=2).delete()


# --- Reviews whose brand is unavailable ---------------------------------------


@pytest.mark.parametrize("brand_reference", [99, "", "not-a-number"])
def test_review_with_unavailable_brand_is_skipped_and_reported(brand_reference):
    report = import_snapshot(
        snapshot(reviews=[review(12), review(13, brand_id=brand_reference)])
    )

    assert list(Review.objects.values_list("wp_post_id", flat=True)) == [12]
    assert [(s.post_id, s.brand_reference) for s in report.skipped_reviews] == [
        (13, str(brand_reference))
    ]


def test_author_of_only_skipped_reviews_does_not_become_a_reviewer():
    import_snapshot(
        snapshot(reviews=[review(13, brand_id=99, author_id=9, author="Kenji O.")])
    )

    assert not Reviewer.objects.filter(wp_user_id=9).exists()


def test_review_moved_to_an_unavailable_brand_is_reported_kept_then_pruned():
    import_snapshot(snapshot(reviews=[review(12, brand_id=7)]))
    moved = snapshot(reviews=[review(12, brand_id=99)])

    report = import_snapshot(moved)
    assert [s.post_id for s in report.skipped_reviews] == [12]
    assert report.reviews.missing == [(12, "review-12")]
    # Default is non-destructive: the existing copy is kept unchanged, on its
    # previous brand, and reported.
    kept = Review.objects.get(wp_post_id=12)
    assert kept.brand.wp_post_id == 7

    report = import_snapshot(moved, prune=True)
    assert not Review.objects.filter(wp_post_id=12).exists()
    assert not Reviewer.objects.exists()
    assert report.reviews.deleted == 1
    assert report.reviewers.deleted == len(report.reviewers.missing) == 1


# --- Slug reuse ------------------------------------------------------------------


def test_slug_reused_by_a_new_post_aborts_without_prune_and_names_both_posts():
    import_snapshot(snapshot(brands=[brand(7, "acme")], reviews=[]))

    with pytest.raises(SourceDataError, match="'acme' now belongs to WordPress ID 9"):
        import_snapshot(snapshot(brands=[brand(9, "acme")], reviews=[]))

    assert list(Brand.objects.values_list("wp_post_id", flat=True)) == [7]


# (first import, second import, model, source-ID field, ID of the new owner)
SLUG_REUSE_CASES = {
    "industry": (
        snapshot(industries=[industry(2, "shared")], brands=[], reviews=[]),
        snapshot(industries=[industry(3, "shared")], brands=[], reviews=[]),
        Industry,
        "wp_term_id",
        3,
    ),
    "review": (
        snapshot(reviews=[review(12, "shared")]),
        snapshot(reviews=[review(13, "shared")]),
        Review,
        "wp_post_id",
        13,
    ),
    # The slug holder is a review skipped because its brand is no longer
    # imported; its Django copy is kept as missing.
    "skipped review": (
        snapshot(reviews=[review(12, "shared")]),
        snapshot(reviews=[review(12, "shared", brand_id=99), review(13, "shared")]),
        Review,
        "wp_post_id",
        13,
    ),
}


@pytest.mark.parametrize("case", SLUG_REUSE_CASES)
def test_slug_reuse_aborts_without_prune_and_imports_with_prune(case):
    first, second, model, id_field, new_id = SLUG_REUSE_CASES[case]
    import_snapshot(first)
    before = sorted(model.objects.values_list(id_field, flat=True))

    with pytest.raises(SourceDataError, match=f"now belongs to WordPress ID {new_id},"):
        import_snapshot(second)
    assert sorted(model.objects.values_list(id_field, flat=True)) == before

    import_snapshot(second, prune=True)
    assert dict(model.objects.values_list(id_field, "slug")) == {new_id: "shared"}


def test_slug_reused_by_a_new_post_imports_with_prune():
    import_snapshot(snapshot(brands=[brand(7, "acme")], reviews=[]))

    import_snapshot(snapshot(brands=[brand(9, "acme")], reviews=[]), prune=True)

    assert dict(Brand.objects.values_list("wp_post_id", "slug")) == {9: "acme"}


# --- Postmeta ----------------------------------------------------------------


def test_mapped_and_dropped_meta_produce_no_warnings():
    report = import_snapshot(TWO_BRANDS)

    assert report.unknown_meta == {}


def test_unknown_meta_is_reported_with_post_counts_and_not_stored():
    report = import_snapshot(
        snapshot(
            brands=[brand(meta={**brand().meta, "_edit_lock": "UNIQUE-LOCK-VALUE"})],
            reviews=[
                review(12, extra_meta={"helpful_votes": "UNIQUE-VOTES-VALUE"}),
                review(13, extra_meta={"helpful_votes": "UNIQUE-VOTES-VALUE"}),
            ],
        )
    )

    assert report.unknown_meta == {
        ("brand", "_edit_lock"): 1,
        ("review", "helpful_votes"): 2,
    }
    for model in (Brand, Review, Industry, Reviewer):
        assert not any(
            isinstance(f, models.JSONField) for f in model._meta.get_fields()
        )
        for row in model.objects.values():
            assert "UNIQUE-" not in str(row)


# --- Missing source entities ---------------------------------------------------

FULL = snapshot(
    industries=[industry(2, "insurance"), industry(3, "telecom")],
    brands=[brand(7, "acme"), brand(8, "swift", industries=(3,))],
    reviews=[
        review(12, brand_id=7, author_id=2, author="Sarah K."),
        review(13, brand_id=7, author_id=3, author="Mike T."),
        review(14, brand_id=8, author_id=4, author="Jenny W."),
        review(15, brand_id=7, author_id=5, author="David L."),
    ],
)

# Brand 8 (with review 14 by author 4), industry 3 and review 15 (author 5's only
# review) have disappeared from WordPress.
REDUCED = snapshot(
    industries=[industry(2, "insurance")],
    brands=[brand(7, "acme")],
    reviews=[
        review(12, brand_id=7, author_id=2, author="Sarah K."),
        review(13, brand_id=7, author_id=3, author="Mike T."),
    ],
)


def test_missing_source_entities_are_reported_and_kept_by_default():
    import_snapshot(FULL)

    report = import_snapshot(REDUCED)

    assert report.industries.missing == [(3, "telecom")]
    assert report.brands.missing == [(8, "swift")]
    assert report.reviews.missing == [(14, "review-14"), (15, "review-15")]
    assert report.reviewers.missing == [(4, "Jenny W."), (5, "David L.")]
    assert Industry.objects.count() == 2
    assert Brand.objects.count() == 2
    assert Review.objects.count() == 4
    assert Reviewer.objects.count() == 4
    assert not report.changed


def test_prune_deletes_exactly_the_missing_entities():
    import_snapshot(FULL)

    report = import_snapshot(REDUCED, prune=True)

    assert list(Industry.objects.values_list("wp_term_id", flat=True)) == [2]
    assert list(Brand.objects.values_list("wp_post_id", flat=True)) == [7]
    assert sorted(Review.objects.values_list("wp_post_id", flat=True)) == [12, 13]
    assert sorted(Reviewer.objects.values_list("wp_user_id", flat=True)) == [2, 3]
    assert (
        report.industries.deleted,
        report.brands.deleted,
        report.reviews.deleted,
        report.reviewers.deleted,
    ) == (1, 1, 2, 2)
    assert report.reviewers.deleted == len(report.reviewers.missing)


def test_prune_deletes_a_missing_brand_with_its_reviews():
    import_snapshot(FULL)

    import_snapshot(changed(FULL, brands=[brand(7, "acme")]), prune=True)

    assert not Brand.objects.filter(wp_post_id=8).exists()
    # Review 14 is still in WordPress but its brand is gone: skipped, and its
    # Django copy went with the brand.
    assert not Review.objects.filter(wp_post_id=14).exists()


def test_prune_removes_a_missing_industry_from_its_brands():
    source = snapshot(
        industries=[industry(2, "insurance"), industry(3, "telecom")],
        brands=[brand(industries=(2, 3))],
    )
    import_snapshot(source)

    import_snapshot(
        changed(
            source,
            industries=[industry(2, "insurance")],
            brands=[brand(industries=(2,))],
        ),
        prune=True,
    )

    assert industries_of(7) == ["insurance"]
    assert not Industry.objects.filter(wp_term_id=3).exists()


def test_prune_keeps_a_reviewer_who_still_has_reviews():
    import_snapshot(FULL)

    import_snapshot(changed(FULL, reviews=FULL.reviews[:3]), prune=True)

    assert Reviewer.objects.filter(wp_user_id=2).exists()
    assert not Reviewer.objects.filter(wp_user_id=5).exists()


def test_reviewer_orphaned_by_an_author_change_is_reported_and_pruned():
    import_snapshot(snapshot(reviews=[review(12, author_id=2, author="Sarah K.")]))

    report = import_snapshot(
        snapshot(reviews=[review(12, author_id=3, author="Mike T.")])
    )
    assert report.reviewers.missing == [(2, "Sarah K.")]
    assert Reviewer.objects.filter(wp_user_id=2).exists()

    import_snapshot(
        snapshot(reviews=[review(12, author_id=3, author="Mike T.")]), prune=True
    )
    assert not Reviewer.objects.filter(wp_user_id=2).exists()


# --- Transactions --------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_failed_import_leaves_nothing_committed():
    source = snapshot(
        reviews=[review(12), review(13, rating="not-a-rating")],
    )

    with pytest.raises(SourceDataError):
        import_snapshot(source)

    assert not Industry.objects.exists()
    assert not Brand.objects.exists()
    assert not Reviewer.objects.exists()
    assert not Review.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_failed_reimport_keeps_the_previous_content():
    import_snapshot(snapshot())

    with pytest.raises(SourceDataError):
        import_snapshot(
            snapshot(brands=[brand(title="Renamed")], reviews=[review(rating="99")])
        )

    assert Brand.objects.get(wp_post_id=7).name == "Acme Insurance Co."


@pytest.mark.django_db(transaction=True)
def test_failure_during_prune_rolls_back_the_import_and_earlier_deletions(monkeypatch):
    import_snapshot(FULL)
    changed_source = changed(REDUCED, brands=[brand(7, "acme", title="Acme Renamed")])

    original_delete = QuerySet.delete

    def delete_failing_for_reviewers(queryset):
        # The last prune step; reviews, brands and industries have already been
        # deleted when it fails.
        if queryset.model is Reviewer:
            raise RuntimeError("simulated failure while pruning reviewers")
        return original_delete(queryset)

    monkeypatch.setattr(QuerySet, "delete", delete_failing_for_reviewers)

    with pytest.raises(RuntimeError, match="simulated"):
        import_snapshot(changed_source, prune=True)

    monkeypatch.undo()
    assert Brand.objects.get(wp_post_id=7).name == "Acme Insurance Co."
    assert Brand.objects.count() == 2
    assert Industry.objects.count() == 2
    assert Review.objects.count() == 4
    assert Reviewer.objects.count() == 4


# --- Report output -------------------------------------------------------------


def test_report_lists_counts_missing_skips_mismatches_and_unknown_keys():
    import_snapshot(FULL)
    source = changed(
        REDUCED,
        brands=[brand(7, "acme", meta={**brand().meta, "_edit_lock": "1"})],
        reviews=[
            review(
                12, brand_id=7, author_id=2, author="Sarah K.", reviewer_name="Sara"
            ),
            review(13, brand_id=99, author_id=3, author="Mike T."),
        ],
    )

    text = format_report(import_snapshot(source))

    # Review 13 is skipped (brand 99) and its Django copy counts as missing.
    assert "  reviews            0        0          1        3" in text
    assert "Missing from WordPress (kept; --prune deletes them):" in text
    assert "  brands: 8 swift" in text
    assert "review 13 review-13: brand '99'" in text
    assert "review 12: reviewer_name 'Sara', author 'Sarah K.'" in text
    assert "  brand _edit_lock: 1 post(s)" in text
