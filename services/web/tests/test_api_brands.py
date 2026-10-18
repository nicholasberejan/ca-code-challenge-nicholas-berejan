"""GET /api/brands/ and GET /api/industries/ (docs/decisions.md §4)."""

from datetime import timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from django.conf import settings
from django.db import connection
from django.test.utils import CaptureQueriesContext

from content.models import Review

from .factories import T0, make_brand, make_industry, make_review, make_reviewer

pytestmark = pytest.mark.django_db


def get(client, query="", **headers):
    return client.get(f"/api/brands/{query}", **headers)


def slugs(response):
    return [b["slug"] for b in response.json()["results"]]


def only(response):
    (result,) = response.json()["results"]
    return result


# --- Representation ----------------------------------------------------------


def test_result_has_exactly_the_card_fields(client):
    industry = make_industry("insurance")
    make_brand("acme", industries=[industry], ratings=[4, 5])

    result = only(get(client))

    assert set(result) == {
        "name",
        "slug",
        "industries",
        "average_rating",
        "review_count",
        "short_description",
        "top_review",
    }
    assert result["industries"] == [{"slug": "insurance", "name": "Insurance"}]
    assert result["short_description"] == "Short description of acme."
    assert set(result["top_review"]) == {
        "slug",
        "title",
        "rating",
        "reviewer_name",
        "snippet",
    }


def test_industries_are_sorted_by_name(client):
    zed, alpha = make_industry("z", "Zed"), make_industry("a", "Alpha")
    make_brand("acme", industries=[zed, alpha])

    assert only(get(client))["industries"] == [
        {"slug": "a", "name": "Alpha"},
        {"slug": "z", "name": "Zed"},
    ]


# --- Derived aggregates --------------------------------------------------------


def test_rating_and_count_are_derived_from_reviews_not_the_legacy_value(client):
    make_brand("acme", ratings=[4] * 12, legacy_average_rating=Decimal("1.00"))

    result = only(get(client))

    assert result["review_count"] == 12
    assert result["average_rating"] == 4.0
    assert "legacy_average_rating" not in result


def test_average_is_a_json_number_rounded_to_two_decimals(client):
    make_brand("acme", ratings=[4] * 11 + [3])  # 47 / 12 = 3.91666...

    response = get(client)

    assert only(response)["average_rating"] == 3.92
    assert '"average_rating":3.92' in response.content.decode()


def test_brand_without_reviews_has_null_average_zero_count_and_no_top_review(client):
    make_brand("empty")

    result = only(get(client))

    assert result["average_rating"] is None
    assert result["review_count"] == 0
    assert result["top_review"] is None


def test_ordering_by_rating_uses_the_derived_value_not_legacy(client):
    make_brand("legacy-high", ratings=[2, 2], legacy_average_rating=Decimal("5.00"))
    make_brand("legacy-low", ratings=[4, 4], legacy_average_rating=Decimal("1.00"))

    assert slugs(get(client)) == ["legacy-low", "legacy-high"]


# --- Industry filtering --------------------------------------------------------


def test_brand_in_two_requested_industries_appears_once_without_inflation(client):
    a, b = make_industry("a"), make_industry("b")
    ratings = [5, 4, 4, 3, 5, 2, 4, 4, 5, 3, 4, 1]  # 44 / 12 = 3.67
    make_brand("both", industries=[a, b], ratings=ratings)

    result = only(get(client, "?industry=a&industry=b"))

    assert result["slug"] == "both"
    assert result["review_count"] == 12
    assert result["average_rating"] == 3.67
    assert result["top_review"] is not None
    assert get(client, "?industry=a&industry=b").json()["count"] == 1


def test_single_industry_filter(client):
    a, b = make_industry("a"), make_industry("b")
    make_brand("in-a", industries=[a])
    make_brand("in-b", industries=[b])

    assert slugs(get(client, "?industry=a")) == ["in-a"]


def test_multiple_industries_mean_any_of_them(client):
    a, b, c = make_industry("a"), make_industry("b"), make_industry("c")
    make_brand("in-a", industries=[a])
    make_brand("in-b", industries=[b])
    make_brand("in-c", industries=[c])

    assert sorted(slugs(get(client, "?industry=a&industry=b"))) == ["in-a", "in-b"]


def test_duplicate_industry_values_are_harmless(client):
    a = make_industry("a")
    make_brand("in-a", industries=[a], ratings=[3, 4])

    result = only(get(client, "?industry=a&industry=a"))

    assert result["review_count"] == 2


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ("?industry=nope", "Unknown industry: 'nope'."),
        ("?industry=a&industry=nope", "Unknown industry: 'nope'."),
        ("?industry=", "Unknown industry: ''."),
    ],
)
def test_unknown_industry_is_rejected_with_the_error_shape(client, query, message):
    make_industry("a")

    response = get(client, query)

    assert response.status_code == 400
    assert response.json() == {"errors": {"industry": [message]}}


# --- Ordering ------------------------------------------------------------------


@pytest.fixture
def rated_brands():
    make_brand("mid", ratings=[3, 4])  # 3.5, 2 reviews
    make_brand("top", ratings=[5])  # 5.0, 1 review
    make_brand("low", ratings=[1, 2, 3])  # 2.0, 3 reviews
    make_brand("none")  # no reviews


@pytest.mark.parametrize(
    ("ordering", "expected"),
    [
        ("", ["top", "mid", "low", "none"]),
        ("?ordering=-average_rating", ["top", "mid", "low", "none"]),
        ("?ordering=average_rating", ["low", "mid", "top", "none"]),
        ("?ordering=-review_count", ["low", "mid", "top", "none"]),
        ("?ordering=review_count", ["none", "top", "mid", "low"]),
    ],
)
def test_supported_orderings(client, rated_brands, ordering, expected):
    assert slugs(get(client, ordering)) == expected


def test_brands_without_reviews_sort_last_in_both_rating_directions(client):
    make_brand("a-none")
    make_brand("b-rated", ratings=[1])
    make_brand("c-none")

    assert slugs(get(client, "?ordering=average_rating")) == [
        "b-rated",
        "a-none",
        "c-none",
    ]
    assert slugs(get(client, "?ordering=-average_rating")) == [
        "b-rated",
        "a-none",
        "c-none",
    ]


def test_rating_order_uses_the_unrounded_average(client):
    # Both display as 3.90; underneath 82/21 = 3.9048 > 39/10 = 3.9000. Sorting
    # on the rounded value would fall back to slug order (aaa first).
    make_brand("aaa-lower", ratings=[4] * 9 + [3])
    make_brand("zzz-higher", ratings=[4] * 19 + [3, 3])

    response = get(client)

    assert [b["average_rating"] for b in response.json()["results"]] == [3.9, 3.9]
    assert slugs(response) == ["zzz-higher", "aaa-lower"]
    assert slugs(get(client, "?ordering=average_rating")) == ["aaa-lower", "zzz-higher"]


def test_ties_are_broken_by_slug(client):
    for slug in ["charlie", "alpha", "bravo"]:
        make_brand(slug, ratings=[4, 4])

    for ordering in [
        "",
        "?ordering=average_rating",
        "?ordering=review_count",
        "?ordering=-review_count",
    ]:
        assert slugs(get(client, ordering)) == ["alpha", "bravo", "charlie"]


def test_unknown_ordering_is_rejected_with_the_error_shape(client):
    response = get(client, "?ordering=name")

    assert response.status_code == 400
    assert response.json() == {
        "errors": {"ordering": ['"name" is not a valid choice.']}
    }


# --- Pagination ----------------------------------------------------------------


@pytest.fixture
def thirteen_brands():
    for n in range(13):
        make_brand(f"brand-{n:02d}")


def test_default_page_size_is_12_with_envelope(client, thirteen_brands):
    body = get(client).json()

    assert set(body) == {"count", "next", "previous", "results"}
    assert body["count"] == 13
    assert len(body["results"]) == 12
    assert body["next"] == "http://testserver/api/brands/?page=2"
    assert body["previous"] is None


def parsed(url):
    parts = urlsplit(url)
    return parts.scheme, parts.netloc, parts.path, parse_qs(parts.query)


def test_page_navigation_keeps_other_parameters(client, thirteen_brands):
    body = get(client, "?ordering=review_count&page_size=5&page=2").json()

    assert [b["slug"] for b in body["results"]] == [
        f"brand-{n:02d}" for n in range(5, 10)
    ]
    assert parsed(body["next"]) == (
        "http",
        "testserver",
        "/api/brands/",
        {"ordering": ["review_count"], "page_size": ["5"], "page": ["3"]},
    )
    assert parsed(body["previous"]) == (
        "http",
        "testserver",
        "/api/brands/",
        {"ordering": ["review_count"], "page_size": ["5"]},
    )


def test_last_page(client, thirteen_brands):
    body = get(client, "?page=2").json()

    assert [b["slug"] for b in body["results"]] == ["brand-12"]
    assert body["next"] is None
    assert body["previous"] == "http://testserver/api/brands/"


def test_maximum_page_size_is_allowed(client, thirteen_brands):
    assert len(get(client, "?page_size=50").json()["results"]) == 13


@pytest.mark.parametrize(
    ("query", "param", "message"),
    [
        (
            "?page_size=51",
            "page_size",
            "Ensure this value is less than or equal to 50.",
        ),
        (
            "?page_size=0",
            "page_size",
            "Ensure this value is greater than or equal to 1.",
        ),
        ("?page_size=ten", "page_size", "A valid integer is required."),
        ("?page=0", "page", "Ensure this value is greater than or equal to 1."),
        ("?page=two", "page", "A valid integer is required."),
    ],
)
def test_invalid_pagination_parameters_are_rejected(client, query, param, message):
    response = get(client, query)

    assert response.status_code == 400
    assert response.json() == {"errors": {param: [message]}}


def test_out_of_range_page_is_404(client, thirteen_brands):
    response = get(client, "?page=3")

    assert response.status_code == 404
    assert response.json() == {"errors": {"page": ["Page out of range."]}}


def test_first_page_of_an_empty_result_is_200(client):
    body = get(client).json()

    assert body == {"count": 0, "next": None, "previous": None, "results": []}


def test_all_invalid_parameters_are_reported_together(client):
    response = get(client, "?industry=nope&ordering=x&page_size=0")

    assert response.status_code == 400
    assert set(response.json()["errors"]) == {"industry", "ordering", "page_size"}


# --- Top review ----------------------------------------------------------------


def brand_with(ratings, **kwargs):
    brand = make_brand("acme", **kwargs)
    reviewer = make_reviewer()
    return brand, [
        make_review(brand, r, published_at=T0 + timedelta(days=i), reviewer=reviewer)
        for i, r in enumerate(ratings)
    ]


def top_rating(client):
    return only(get(client))["top_review"]["rating"]


def test_top_review_is_the_strictly_closest_even_above_the_mean(client):
    brand_with([3, 4, 4, 4, 3])  # mean 3.6: 4 is 0.4 away, 3 is 0.6 away

    assert top_rating(client) == 4


def test_equally_distant_ratings_prefer_the_lower_one(client):
    brand_with([3, 4])  # mean 3.5

    assert top_rating(client) == 3


def test_top_review_uses_the_exact_mean_not_the_rounded_one(client):
    # 704 / 201 = 3.5025 (rounded 3.50): 4 is strictly closer than 3. Using the
    # rounded mean would see a tie and pick 3.
    brand = make_brand("acme")
    reviewer = make_reviewer()
    Review.objects.bulk_create(
        Review(
            wp_post_id=10_000 + n,
            slug=f"bulk-{n}",
            title="t",
            content="",
            rating=4 if n < 101 else 3,
            published_at=T0,
            brand=brand,
            reviewer=reviewer,
        )
        for n in range(201)
    )

    result = only(get(client))
    assert result["average_rating"] == 3.5
    assert result["top_review"]["rating"] == 4


def test_remaining_ties_prefer_the_newest_then_the_lowest_wordpress_id(client):
    brand = make_brand("acme")
    reviewer = make_reviewer()
    make_review(
        brand, 4, published_at=T0, wp_post_id=501, reviewer=reviewer, title="Old"
    )
    make_review(
        brand,
        4,
        published_at=T0 + timedelta(days=1),
        wp_post_id=502,
        reviewer=reviewer,
        title="Newest A",
    )
    make_review(
        brand,
        4,
        published_at=T0 + timedelta(days=1),
        wp_post_id=500,
        reviewer=reviewer,
        title="Newest B",
    )

    assert only(get(client))["top_review"]["title"] == "Newest B"


def test_top_review_snippet_is_plain_text_of_about_160_characters(client):
    brand = make_brand("acme")
    words = " ".join(["word"] * 60)
    make_review(
        brand,
        4,
        reviewer=make_reviewer("Mike T."),
        title="Great",
        content=f"<p>Fast &amp; <strong>friendly</strong>. {words}</p>",
    )

    top = only(get(client))["top_review"]

    assert top["reviewer_name"] == "Mike T."
    assert top["title"] == "Great"
    assert top["snippet"].startswith("Fast & friendly. word word")
    assert top["snippet"].endswith("…")
    assert len(top["snippet"]) <= 161
    assert "<" not in top["snippet"]


# --- Query efficiency ------------------------------------------------------------


def count_queries(client, query=""):
    with CaptureQueriesContext(connection) as queries:
        assert get(client, query).status_code == 200
    return len(queries)


def test_query_count_does_not_grow_with_the_number_of_brands(client):
    industry = make_industry("a")
    for n in range(2):
        make_brand(f"small-{n}", industries=[industry], ratings=[3, 4, 5])
    few = count_queries(client, "?industry=a")

    for n in range(8):
        make_brand(f"more-{n}", industries=[industry], ratings=[1, 2, 3, 4])
    many = count_queries(client, "?industry=a")

    assert many == few


# --- Industries endpoint ---------------------------------------------------------


def test_industries_endpoint_lists_every_industry_by_name(client):
    make_industry("telecom", "Telecom")
    used = make_industry("finance", "Finance")
    make_industry("retail", "Retail")
    for n in range(13):
        make_brand(f"bank-{n}", industries=[used])

    response = client.get("/api/industries/")

    assert response.status_code == 200
    assert response.json() == [
        {"slug": "finance", "name": "Finance"},
        {"slug": "retail", "name": "Retail"},
        {"slug": "telecom", "name": "Telecom"},
    ]


def test_industries_endpoint_ignores_brand_filters_and_pages(client):
    make_industry("a")
    make_industry("b")

    response = client.get("/api/industries/?industry=a&page=9")

    assert [i["slug"] for i in response.json()] == ["a", "b"]


# --- Public, read-only, auth-independent -----------------------------------------


def test_no_authentication_is_configured_for_the_public_api():
    assert settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] == []


@pytest.mark.parametrize("path", ["/api/brands/", "/api/industries/"])
def test_public_endpoints_ignore_credentials(client, path):
    assert client.get(path, HTTP_AUTHORIZATION="Bearer not-a-token").status_code == 200
