from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    # Immutable WordPress source identity, used by the user import. Null for
    # accounts created directly in this service.
    wp_user_id = models.PositiveBigIntegerField(unique=True, null=True, blank=True)
