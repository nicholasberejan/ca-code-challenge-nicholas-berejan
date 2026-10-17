"""The single HTML sanitizer for externally sourced content (docs/decisions.md §9).

Any code path that persists HTML must pass it through `sanitize_html` first.
"""

import html
import re

import nh3

ALLOWED_TAGS = frozenset(
    {"p", "br", "strong", "em", "a", "ul", "ol", "li", "blockquote", "h2", "h3", "h4"}
)
# "*": no attribute is allowed on every tag (nh3 otherwise allows `lang` and
# `title` everywhere).
ALLOWED_ATTRIBUTES: dict[str, frozenset[str]] = {
    "*": frozenset(),
    "a": frozenset({"href"}),
}
ALLOWED_URL_SCHEMES = frozenset({"http", "https", "mailto"})

SHORT_DESCRIPTION_WORDS = 22

# Tags whose boundaries separate words; used when flattening HTML to text so
# "<p>one</p><p>two</p>" becomes "one two", not "onetwo".
_BLOCK_BOUNDARY = re.compile(r"<(?=/?(?:p|br|li|h[1-6]|blockquote|div)\b)", re.I)


def sanitize_html(value: str) -> str:
    """Keep only the allowlisted tags, `href` on links and safe URL schemes.

    `<script>`/`<style>` are removed with their content; event-handler and
    `style` attributes, other tags and disallowed link schemes are dropped.
    """
    return nh3.clean(
        value,
        tags=set(ALLOWED_TAGS),
        attributes={tag: set(attrs) for tag, attrs in ALLOWED_ATTRIBUTES.items()},
        url_schemes=set(ALLOWED_URL_SCHEMES),
        # Without this nh3 adds rel="noopener noreferrer"; `href` is the only
        # attribute allowed on links.
        link_rel=None,
    )


def html_to_text(value: str) -> str:
    """Plain text from HTML: tags (and script/style content) removed,
    entities decoded, whitespace collapsed."""
    spaced = _BLOCK_BOUNDARY.sub(" <", value)
    text = html.unescape(nh3.clean(spaced, tags=set()))
    return " ".join(text.split())


def summarize(value: str, words: int = SHORT_DESCRIPTION_WORDS) -> str:
    """The first `words` words of the text, with an ellipsis if truncated.

    Mirrors the WordPress theme's `wp_trim_words(..., 22)` card excerpt.
    """
    parts = html_to_text(value).split()
    if len(parts) <= words:
        return " ".join(parts)
    return " ".join(parts[:words]) + "…"
