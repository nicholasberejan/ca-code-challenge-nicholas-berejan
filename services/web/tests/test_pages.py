"""Public server-rendered pages."""

import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from .factories import T0, make_brand, make_industry, make_review, make_reviewer

pytestmark = pytest.mark.django_db


def html(response):
    assert response.status_code == 200
    return response.content.decode()


def review_titles(page):
    return re.findall(r'class="review-item__title"><a href="[^"]+">([^<]+)</a>', page)


# --- Navigation ----------------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/brand/"])
def test_navigation_links_home_and_brand_listing_only(client, path):
    page = html(client.get(path))
    nav = page[page.index('<nav class="site-nav"') : page.index("</nav>")]

    assert re.findall(r'href="([^"]+)"', nav) == ["/", "/brand/"]
    assert 'aria-current="page"' in nav


# --- Homepage --------------------------------------------------------------------


def test_homepage_has_a_hero_and_the_six_newest_reviews(client):
    brand = make_brand("acme", name="Acme Insurance")
    reviewer = make_reviewer("Jenny W.")
    for day in range(8):
        make_review(
            brand,
            4,
            published_at=T0 + timedelta(days=day),
            reviewer=reviewer,
            title=f"Day {day}",
        )

    page = html(client.get("/"))

    assert '<section class="hero"' in page
    assert "Honest reviews of consumer brands</h1>" in page
    assert (
        "Independent customer feedback on insurance, telecom, finance, home "
        "services, and retail companies." in page
    )
    assert 'class="hero__cta" href="/brand/"' in page
    assert review_titles(page) == [f"Day {d}" for d in (7, 6, 5, 4, 3, 2)]
    assert "Jenny W." in page
    assert 'href="/brand/acme/"' in page


def test_homepage_query_count_does_not_grow_with_reviews(client):
    brand = make_brand("acme")
    make_review(brand, 4)
    with CaptureQueriesContext(connection) as one:
        html(client.get("/"))

    for n in range(5):
        make_review(make_brand(f"other-{n}"), 3, reviewer=make_reviewer(f"R{n}"))
    with CaptureQueriesContext(connection) as six:
        html(client.get("/"))

    assert len(six) == len(one)


def test_homepage_breaks_publish_time_ties_by_wordpress_id(client):
    brand = make_brand("acme")
    for post_id in (702, 700, 701):
        make_review(brand, 4, wp_post_id=post_id, title=f"Post {post_id}")

    assert review_titles(html(client.get("/"))) == ["Post 700", "Post 701", "Post 702"]


# --- Brand page ------------------------------------------------------------------


@pytest.fixture
def acme():
    industries = [
        make_industry("telecom", "Telecom"),
        make_industry("finance", "Finance"),
    ]
    brand = make_brand(
        "acme",
        name="Acme Insurance",
        industries=industries,
        content="<p>Founded in <strong>Hartford</strong>.</p>",
        website_url="https://acme.example.com",
        founded_year=1985,
        headquarters="Hartford, CT",
        legacy_average_rating=Decimal("1.00"),
    )
    old, new = make_reviewer("Old Reviewer"), make_reviewer("New Reviewer")
    for day, rating in enumerate([4] * 11 + [3]):  # 47 / 12 = 3.9
        make_review(
            brand,
            rating,
            published_at=T0 + timedelta(days=day),
            reviewer=new if day == 11 else old,
            title=f"Review day {day}",
        )
    return brand


def test_brand_page_shows_the_brand_and_its_derived_rating(client, acme):
    page = html(client.get("/brand/acme/"))

    assert "<title>Acme Insurance | Brand Reviews</title>" in page
    assert '<meta name="description" content="Short description of acme.">' in page
    assert "<h1" in page and "Acme Insurance</h1>" in page
    assert re.findall(r'<li class="badge">([^<]+)</li>', page) == ["Finance", "Telecom"]
    assert "Rated 3.9 out of 5 from 12 reviews" in page
    assert "1.0" not in page  # the legacy value is never shown
    assert 'href="https://acme.example.com"' in page
    assert "<dd>1985</dd>" in page and "<dd>Hartford, CT</dd>" in page


def test_brand_page_renders_the_sanitized_body_as_html(client, acme):
    page = html(client.get("/brand/acme/"))

    assert "<p>Founded in <strong>Hartford</strong>.</p>" in page


def test_brand_page_lists_all_reviews_newest_first_with_reviewers(client, acme):
    page = html(client.get("/brand/acme/"))

    assert review_titles(page) == [f"Review day {d}" for d in range(11, -1, -1)]
    assert "New Reviewer" in page and "Old Reviewer" in page


def test_brand_without_reviews(client):
    make_brand("empty")

    page = html(client.get("/brand/empty/"))

    assert "No reviews yet" in page


def test_unknown_brand_is_404(client):
    assert client.get("/brand/nope/").status_code == 404


def test_brand_page_query_count_does_not_grow_with_reviews(client, acme):
    make_brand("small", ratings=[4, 5])

    with CaptureQueriesContext(connection) as small:
        html(client.get("/brand/small/"))
    with CaptureQueriesContext(connection) as large:
        html(client.get("/brand/acme/"))

    assert len(large) == len(small)


# --- Review page -----------------------------------------------------------------


def test_review_page_shows_the_review(client):
    brand = make_brand("acme", name="Acme Insurance")
    make_review(
        brand,
        2,
        wp_post_id=900,
        reviewer=make_reviewer("Anna R."),
        title="Slow claim",
        location="Tucson, AZ",
        published_at=T0,
        content="<p>Took <em>weeks</em>.</p>",
    )

    page = html(client.get("/review/review-900/"))

    assert 'href="/brand/acme/"' in page and "Back to Acme Insurance" in page
    assert "Slow claim</h1>" in page
    assert "Rated 2 out of 5" in page
    assert "By Anna R., Tucson, AZ" in page
    assert '<time datetime="2026-01-01T12:00:00+00:00">1 January 2026</time>' in page
    assert "<p>Took <em>weeks</em>.</p>" in page


def test_unknown_review_is_404(client):
    assert client.get("/review/nope/").status_code == 404


# --- Brand listing host ------------------------------------------------------------


def test_brand_listing_host_has_the_mount_point_and_no_brand_data(client):
    make_brand("acme", name="Acme Insurance", ratings=[4])

    page = html(client.get("/brand/"))

    assert '<div id="brand-list"></div>' in page
    assert 'src="/static/frontend/brand-list.js"' in page
    assert "Acme Insurance" not in page
    assert "acme" not in page


# --- Escaping ----------------------------------------------------------------------


def test_plain_text_fields_are_escaped_and_only_bodies_render_html(client):
    industry = make_industry("evil", "<b>Industry</b>")
    brand = make_brand(
        "evil",
        name="<script>alert('name')</script>",
        short_description='"><script>alert("desc")</script>',
        headquarters="<i>HQ</i>",
        industries=[industry],
        content="<p>Safe body</p>",
    )
    make_review(
        brand,
        3,
        wp_post_id=901,
        reviewer=make_reviewer("<img src=x onerror=alert(1)>"),
        title="<u>Title</u>",
        location="<s>Somewhere</s>",
        content="<p>Plain &amp; safe</p>",
    )

    pages = [
        html(client.get("/brand/evil/")),
        html(client.get("/review/review-901/")),
        html(client.get("/")),
    ]

    joined = "\n".join(pages)
    for raw in [
        "<script>alert",
        "<b>Industry</b>",
        "<i>HQ</i>",
        "<img src=x",
        "<u>Title</u>",
        "<s>Somewhere</s>",
        '"><script>',
    ]:
        assert raw not in joined, raw
    assert "&lt;script&gt;alert(&#x27;name&#x27;)&lt;/script&gt;" in pages[0]
    assert "&lt;b&gt;Industry&lt;/b&gt;" in pages[0]
    assert "&lt;img src=x onerror=alert(1)&gt;" in pages[1]
    assert "<p>Safe body</p>" in pages[0]
    assert "<p>Plain &amp; safe</p>" in pages[1]
