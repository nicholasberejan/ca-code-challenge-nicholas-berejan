"""Content domain migrated from WordPress (docs/decisions.md §1).

Every imported row keeps its immutable WordPress ID as its source identity.
Slugs are public routing identifiers that follow WordPress and may change.
Slug uniqueness is checked at commit time so an import that swaps two slugs
inside one transaction does not fail halfway.
"""

from django.db import models


def _unique_slug(model: str) -> models.UniqueConstraint:
    return models.UniqueConstraint(
        fields=["slug"],
        name=f"{model}_slug_unique",
        deferrable=models.Deferrable.DEFERRED,
    )


class Industry(models.Model):
    wp_term_id = models.PositiveBigIntegerField(unique=True)
    slug = models.SlugField(max_length=200, db_index=False)
    name = models.CharField(max_length=200)

    class Meta:
        constraints = [_unique_slug("industry")]
        ordering = ["name"]
        verbose_name_plural = "industries"

    def __str__(self) -> str:
        return self.name


class Brand(models.Model):
    wp_post_id = models.PositiveBigIntegerField(unique=True)
    slug = models.SlugField(max_length=200, db_index=False)
    name = models.CharField(max_length=255)
    # Sanitized at import (docs/decisions.md §9); never raw WordPress HTML.
    content = models.TextField(blank=True)
    website_url = models.URLField(max_length=500, blank=True)
    founded_year = models.PositiveSmallIntegerField(null=True, blank=True)
    headquarters = models.CharField(max_length=255, blank=True)
    # WordPress's stored average, kept for audit only. The current average is
    # always derived from Review rows.
    legacy_average_rating = models.DecimalField(
        max_digits=3, decimal_places=2, null=True, blank=True
    )
    # Django-owned: seeded when the brand is first imported, never overwritten
    # by a later import.
    short_description = models.TextField()
    published_at = models.DateTimeField()
    industries = models.ManyToManyField(Industry, related_name="brands", blank=True)

    class Meta:
        constraints = [_unique_slug("brand")]

    def __str__(self) -> str:
        return self.name


class Reviewer(models.Model):
    """The public persona of a review author; not an account."""

    wp_user_id = models.PositiveBigIntegerField(unique=True)
    display_name = models.CharField(max_length=250)

    def __str__(self) -> str:
        return self.display_name


class Review(models.Model):
    wp_post_id = models.PositiveBigIntegerField(unique=True)
    slug = models.SlugField(max_length=200, db_index=False)
    title = models.CharField(max_length=255)
    # Sanitized at import (docs/decisions.md §9); never raw WordPress HTML.
    content = models.TextField(blank=True)
    rating = models.PositiveSmallIntegerField()
    # Where the reviewed service was used, which can differ per review.
    reviewer_location = models.CharField(max_length=255, blank=True)
    published_at = models.DateTimeField()
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="reviews")
    reviewer = models.ForeignKey(
        Reviewer, on_delete=models.PROTECT, related_name="reviews"
    )

    class Meta:
        constraints = [
            _unique_slug("review"),
            models.CheckConstraint(
                condition=models.Q(rating__gte=1, rating__lte=5),
                name="review_rating_1_to_5",
            ),
        ]

    def __str__(self) -> str:
        return self.title
