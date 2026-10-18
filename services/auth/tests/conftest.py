import pytest
from django.db import DatabaseError, connections

from accounts.wordpress import SourceUser, read_users


@pytest.fixture(scope="session")
def wordpress_users(django_db_blocker) -> dict[str, SourceUser]:
    """The seeded WordPress users (real `$wp$` hashes made by WordPress),
    read through a dedicated read-only connection. Seed passwords:
    admin/admin, every other user `changeme` (scripts/seed.sh)."""
    with django_db_blocker.unblock():
        connection = connections.create_connection("wordpress")
        try:
            users = read_users(connection)
        except DatabaseError as error:
            pytest.fail(
                f"WordPress database unavailable ({error}); start it with "
                "`docker compose up -d db`."
            )
        finally:
            connection.close()
    return {user.login: user for user in users}
