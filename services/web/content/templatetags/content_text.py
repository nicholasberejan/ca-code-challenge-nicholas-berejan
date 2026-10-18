import math
from decimal import ROUND_HALF_UP, Decimal

from django import template

from content.sanitize import snippet as plain_snippet

register = template.Library()


@register.filter
def snippet(value: str, limit: int = 160) -> str:
    """Plain-text excerpt of stored HTML. The result is ordinary text and is
    autoescaped like any other value."""
    return plain_snippet(value, int(limit))


@register.inclusion_tag("partials/stars.html")
def stars(
    rating: float | Decimal | int | None, show_value: bool = True
) -> dict[str, object]:
    """Star rating like the WordPress theme's cr_stars(): whole stars filled,
    the rest empty, with the value to one decimal place."""
    value = max(Decimal(0), min(Decimal(5), Decimal(str(rating or 0))))
    full = math.floor(value)
    return {
        "label": value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
        "full": range(full),
        "empty": range(5 - full),
        "show_value": show_value,
    }
