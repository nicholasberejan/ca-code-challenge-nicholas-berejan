from django import template

from content.sanitize import snippet as plain_snippet

register = template.Library()


@register.filter
def snippet(value: str, limit: int = 160) -> str:
    """Plain-text excerpt of stored HTML. The result is ordinary text and is
    autoescaped like any other value."""
    return plain_snippet(value, int(limit))
