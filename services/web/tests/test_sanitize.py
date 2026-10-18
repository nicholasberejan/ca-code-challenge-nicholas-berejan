"""The HTML sanitizer, and that imported HTML is stored only in sanitized form."""

import pytest

from content.models import Brand, Review
from content.sanitize import html_to_text, sanitize_html, snippet, summarize
from content.wordpress.importer import import_snapshot

from .snapshots import brand, review, snapshot

XSS_PAYLOADS = [
    '<script>alert("x")</script>',
    '<img src="x" onerror="alert(1)">',
    '<p onclick="alert(1)">click</p>',
    '<p style="background:url(javascript:alert(1))">styled</p>',
    '<a href="javascript:alert(1)">js link</a>',
    '<a href="JaVaScRiPt:alert(1)">mixed case</a>',
    '<a href="data:text/html;base64,PHNjcmlwdD4=">data link</a>',
    '<svg onload="alert(1)"><circle /></svg>',
    '<iframe src="https://evil.example"></iframe>',
    "<style>p { color: red }</style>",
    '<a href="https://ok.example" onmouseover="alert(1)" target="_blank">ok</a>',
    '<form action="https://evil.example"><input name="q"></form>',
    '<p title="x" lang="en">generic attributes</p>',
]

FORBIDDEN_FRAGMENTS = [
    "<script",
    "alert(",
    "onerror",
    "onclick",
    "onload",
    "onmouseover",
    "style=",
    "<style",
    "javascript:",
    "data:",
    "<img",
    "<svg",
    "<iframe",
    "<form",
    "<input",
    "target=",
    "title=",
    "lang=",
]


def assert_safe(stored: str) -> None:
    lowered = stored.lower()
    for fragment in FORBIDDEN_FRAGMENTS:
        assert fragment not in lowered, f"{fragment!r} survived in {stored!r}"


@pytest.mark.parametrize("payload", XSS_PAYLOADS)
def test_sanitizer_removes_xss_payload(payload):
    assert_safe(sanitize_html(payload))


def test_sanitizer_keeps_allowlisted_markup():
    allowed = (
        "<h2>Heading</h2><h3>Sub</h3><h4>Minor</h4>"
        "<p>Text with <strong>bold</strong>, <em>italic</em><br>break</p>"
        "<ul><li>one</li></ul><ol><li>two</li></ol>"
        "<blockquote>quote</blockquote>"
        '<p><a href="https://example.com">web</a> '
        '<a href="http://example.com">plain</a> '
        '<a href="mailto:a@example.com">mail</a></p>'
    )

    assert sanitize_html(allowed) == allowed


def test_sanitizer_drops_non_allowlisted_tags_but_keeps_their_text():
    assert sanitize_html('<div class="x"><span>kept</span></div>') == "kept"


def test_links_keep_only_href():
    assert (
        sanitize_html('<a href="https://example.com" title="t" rel="x">link</a>')
        == '<a href="https://example.com">link</a>'
    )


@pytest.mark.django_db
def test_imported_brand_and_review_html_is_stored_sanitized():
    payload = "".join(XSS_PAYLOADS) + "<p>Real <strong>content</strong>.</p>"

    import_snapshot(
        snapshot(brands=[brand(content=payload)], reviews=[review(content=payload)])
    )

    stored_brand = Brand.objects.get(wp_post_id=7).content
    stored_review = Review.objects.get(wp_post_id=12).content
    for stored in (stored_brand, stored_review):
        assert_safe(stored)
        assert "<p>Real <strong>content</strong>.</p>" in stored


@pytest.mark.django_db
def test_reimported_content_is_sanitized_again():
    import_snapshot(snapshot())

    import_snapshot(
        snapshot(
            brands=[
                brand(content='<p onclick="steal()">Updated</p><script>x()</script>')
            ]
        )
    )

    assert Brand.objects.get(wp_post_id=7).content == "<p>Updated</p>"


@pytest.mark.django_db
def test_seeded_short_description_contains_no_markup_or_script_text():
    import_snapshot(
        snapshot(
            brands=[brand(content="<script>evil()</script><p>Safe &amp; sound.</p>")]
        )
    )

    assert Brand.objects.get(wp_post_id=7).short_description == "Safe & sound."


def test_html_to_text_separates_block_elements_and_decodes_entities():
    assert html_to_text("<p>one&nbsp;two</p><p>three &#8211; four</p>") == (
        "one two three – four"
    )


def test_summarize_truncates_to_22_words_with_ellipsis():
    words = " ".join(f"w{i}" for i in range(30))

    assert summarize(f"<p>{words}</p>") == " ".join(f"w{i}" for i in range(22)) + "…"
    assert summarize("<p>short text</p>") == "short text"


# Words end at offsets 8, 15, 22, ... so position 160 falls inside a word:
# a plain 160-character cut would end mid-word.
LONG_TEXT = "a " + " ".join(f"word{i:02d}" for i in range(40))


def test_snippet_keeps_short_text_unchanged_without_ellipsis():
    assert snippet("<p>Short &amp; <em>sweet</em>.</p>") == "Short & sweet."


def test_snippet_keeps_text_of_exactly_160_characters():
    text = "a" * 160

    assert snippet(f"<p>{text}</p>") == text


def test_snippet_cuts_long_text_close_to_160_characters_at_a_word_boundary():
    result = snippet(f"<p>{LONG_TEXT}</p>")

    assert result.endswith("\u2026")
    cut = result.removesuffix("\u2026")
    assert 150 <= len(cut) <= 160
    assert LONG_TEXT.startswith(cut + " ")  # ends on a whole word


def test_snippet_cuts_text_one_character_over_the_limit():
    text = "a" * 156 + " bcde"  # 161 characters

    assert snippet(text) == "a" * 156 + "\u2026"


def test_snippet_cuts_a_long_run_without_spaces_at_160_characters():
    assert snippet("x" * 300) == "x" * 160 + "\u2026"
