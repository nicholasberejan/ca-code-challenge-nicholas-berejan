"""The real WordPress source: read-only access and the seeded data import.

These tests read the repository's seeded WordPress MariaDB (`db` service) and
never write to it. They open their own `wordpress` connection because the
test runner only manages the main database.
"""

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.db import DatabaseError, connections, router
from django.db.models import Avg

from config.routers import WordPressSourceRouter
from content.models import Brand, Industry, Review, Reviewer
from content.sanitize import sanitize_html
from content.wordpress.importer import import_snapshot
from content.wordpress.source import read_snapshot


@contextmanager
def wordpress_connection(django_db_blocker):
    """A dedicated connection to the WordPress source, allowed only here."""
    with django_db_blocker.unblock():
        connection = connections.create_connection("wordpress")
        try:
            connection.ensure_connection()
        except DatabaseError as error:
            pytest.fail(
                f"WordPress database unavailable ({error}); start it with "
                "`docker compose up -d db`."
            )
        try:
            yield connection
        finally:
            connection.close()


@pytest.fixture(scope="module")
def seed(django_db_blocker):
    with wordpress_connection(django_db_blocker) as wordpress:
        return read_snapshot(wordpress)


# --- Read-only access ----------------------------------------------------------


def test_router_never_migrates_or_routes_models_to_wordpress():
    assert WordPressSourceRouter().allow_migrate("wordpress", "content") is False
    assert router.allow_migrate("default", "content") is True
    assert router.db_for_write(Brand) == "default"
    assert router.db_for_read(Brand) == "default"


def test_wordpress_session_rejects_writes(django_db_blocker):
    with (
        wordpress_connection(django_db_blocker) as wordpress,
        pytest.raises(DatabaseError, match="READ ONLY"),
        wordpress.cursor() as cursor,
    ):
        # Touches no rows even if it were allowed.
        cursor.execute("UPDATE wp_options SET option_value = option_value WHERE 1 = 0")


# --- Query rules, on fixture rows ---------------------------------------------

# Session-only temporary tables that hide the real WordPress tables of the
# same name. They need a session without the read-only setting (MariaDB
# refuses even temporary tables in a read-only session); every row inserted
# here goes into a temporary table and disappears when the session closes.
FIXTURE_TABLES = {
    "wp_posts": "ID BIGINT, post_type VARCHAR(20), post_status VARCHAR(20), "
    "post_name VARCHAR(200), post_title TEXT, post_content LONGTEXT, "
    "post_excerpt TEXT, post_date DATETIME, post_date_gmt DATETIME, "
    "post_author BIGINT",
    "wp_postmeta": "meta_id BIGINT AUTO_INCREMENT PRIMARY KEY, post_id BIGINT, "
    "meta_key VARCHAR(255), meta_value LONGTEXT",
    "wp_terms": "term_id BIGINT, slug VARCHAR(200), name VARCHAR(200)",
    "wp_term_taxonomy": "term_taxonomy_id BIGINT, term_id BIGINT, taxonomy VARCHAR(32)",
    "wp_term_relationships": "object_id BIGINT, term_taxonomy_id BIGINT",
    "wp_users": "ID BIGINT, display_name VARCHAR(250)",
}

FIXTURE_ROWS = [
    # Local time 12:00, GMT 17:00: dates must come from post_date_gmt.
    "INSERT INTO wp_posts VALUES "
    "(1, 'brand', 'publish', 'live', 'Live', '<p>x</p>', '', "
    "'2026-01-01 12:00:00', '2026-01-01 17:00:00', 0), "
    "(2, 'brand', 'draft', 'draft-brand', 'Draft', '', '', "
    "'2026-01-01 12:00:00', '2026-01-01 17:00:00', 0), "
    "(3, 'brand', 'private', 'private-brand', 'Private', '', '', "
    "'2026-01-01 12:00:00', '2026-01-01 17:00:00', 0), "
    "(10, 'review', 'publish', 'live-review', 'R', '', '', "
    "'2026-01-02 08:00:00', '2026-01-02 13:00:00', 5), "
    "(11, 'review', 'draft', 'draft-review', 'R', '', '', "
    "'2026-01-02 08:00:00', '2026-01-02 13:00:00', 5), "
    "(12, 'review', 'trash', 'trashed-review', 'R', '', '', "
    "'2026-01-02 08:00:00', '2026-01-02 13:00:00', 5), "
    "(20, 'page', 'publish', 'about', 'About', '', '', "
    "'2026-01-01 12:00:00', '2026-01-01 17:00:00', 0)",
    "INSERT INTO wp_postmeta (post_id, meta_key, meta_value) VALUES "
    "(1, 'headquarters', 'Boston'), (2, 'headquarters', 'Nowhere'), "
    "(10, 'brand', '1'), (11, 'brand', '1')",
    "INSERT INTO wp_terms VALUES (4, 'finance', 'Finance'), (5, 'news', 'News')",
    "INSERT INTO wp_term_taxonomy VALUES (40, 4, 'industry'), (50, 5, 'category')",
    "INSERT INTO wp_term_relationships VALUES (1, 40), (1, 50)",
    "INSERT INTO wp_users VALUES (5, 'Anna R.')",
]


@pytest.fixture
def fixture_source(django_db_blocker):
    settings_dict = deepcopy(connections.settings["wordpress"])
    settings_dict["OPTIONS"].pop("init_command")
    with django_db_blocker.unblock():
        connection = connections["wordpress"].__class__(settings_dict, "wp-fixture")
        try:
            with connection.cursor() as cursor:
                for table, columns in FIXTURE_TABLES.items():
                    cursor.execute(f"CREATE TEMPORARY TABLE {table} ({columns})")
                for statement in FIXTURE_ROWS:
                    cursor.execute(statement)
            yield connection
        finally:
            connection.close()


def test_only_published_brands_reviews_and_industry_terms_are_read(fixture_source):
    source = read_snapshot(fixture_source)

    assert [b.post_id for b in source.brands] == [1]
    assert [r.post_id for r in source.reviews] == [10]
    assert [i.slug for i in source.industries] == ["finance"]
    assert source.brands[0].industry_term_ids == frozenset({4})
    assert source.brands[0].meta == {"headquarters": "Boston"}


def test_dates_come_from_post_date_gmt_as_utc(fixture_source):
    source = read_snapshot(fixture_source)

    assert source.brands[0].published_at == datetime(2026, 1, 1, 17, tzinfo=UTC)
    assert source.reviews[0].published_at == datetime(2026, 1, 2, 13, tzinfo=UTC)


# --- Seeded source facts -------------------------------------------------------


def test_source_reads_only_published_brands_and_reviews(seed):
    assert len(seed.brands) == 5
    assert len(seed.reviews) == 60
    assert len(seed.industries) == 5


def test_source_dates_are_post_date_gmt_in_utc(seed):
    review_12 = next(r for r in seed.reviews if r.post_id == 12)

    assert review_12.published_at == datetime(2026, 5, 19, 20, 29, 13, tzinfo=UTC)


# --- Importing the seed --------------------------------------------------------


@pytest.mark.django_db
def test_seed_imports_with_the_expected_entities_and_relationships(seed):
    report = import_snapshot(seed)

    assert (Brand.objects.count(), Review.objects.count()) == (5, 60)
    assert (Industry.objects.count(), Reviewer.objects.count()) == (5, 8)
    assert report.skipped_reviews == []
    assert report.reviewer_name_mismatches == []
    assert report.unknown_meta == {}

    assert dict(Brand.objects.values_list("wp_post_id", "slug")) == {
        7: "acme-insurance",
        8: "primepath-bank",
        9: "homeshield-pro",
        10: "swiftstream-internet",
        11: "urbanretail-co",
    }
    assert {
        b.slug: [i.slug for i in b.industries.all()]
        for b in Brand.objects.prefetch_related("industries")
    } == {
        "acme-insurance": ["insurance"],
        "primepath-bank": ["finance"],
        "homeshield-pro": ["home-services"],
        "swiftstream-internet": ["telecom"],
        "urbanretail-co": ["retail"],
    }
    assert {b.slug: b.reviews.count() for b in Brand.objects.all()} == dict.fromkeys(
        [
            "acme-insurance",
            "primepath-bank",
            "homeshield-pro",
            "swiftstream-internet",
            "urbanretail-co",
        ],
        12,
    )

    review_12 = Review.objects.select_related("brand", "reviewer").get(wp_post_id=12)
    assert review_12.slug == "smooth-auto-claim-after-a-parking-lot-fender-bender"
    assert review_12.brand.wp_post_id == 7
    assert (review_12.reviewer.wp_user_id, review_12.reviewer.display_name) == (
        2,
        "Sarah K.",
    )
    assert (review_12.rating, review_12.reviewer_location) == (5, "Denver, CO")
    assert Reviewer.objects.get(wp_user_id=2).reviews.count() == 10


@pytest.mark.django_db
def test_seed_content_is_stored_sanitized_with_seeded_short_descriptions(seed):
    import_snapshot(seed)

    sources = {b.post_id: b for b in seed.brands} | {r.post_id: r for r in seed.reviews}
    for item in [*Brand.objects.all(), *Review.objects.all()]:
        assert item.content == sanitize_html(sources[item.wp_post_id].content)
        assert item.content.startswith("<p>")
    for brand in Brand.objects.all():
        words = brand.short_description.rstrip("…").split()
        assert len(words) == 22
        assert "<" not in brand.short_description


@pytest.mark.django_db
def test_seed_legacy_averages_are_retained_but_differ_from_review_averages(seed):
    import_snapshot(seed)

    legacy = dict(Brand.objects.values_list("slug", "legacy_average_rating"))
    assert legacy == {
        "acme-insurance": Decimal("4.20"),
        "primepath-bank": Decimal("4.00"),
        "homeshield-pro": Decimal("3.90"),
        "swiftstream-internet": Decimal("3.50"),
        "urbanretail-co": Decimal("4.40"),
    }
    derived = (
        Brand.objects.annotate(avg=Avg("reviews__rating"))
        .get(slug="homeshield-pro")
        .avg
    )
    assert round(derived, 2) == 3.08


@pytest.mark.django_db
def test_second_seed_import_changes_nothing(seed, django_db_blocker):
    import_snapshot(seed)
    with wordpress_connection(django_db_blocker) as wordpress:
        second_read = read_snapshot(wordpress)

    report = import_snapshot(second_read)

    assert not report.changed
    assert report.brands.unchanged == 5
    assert report.reviews.unchanged == 60
