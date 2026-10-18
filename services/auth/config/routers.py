WORDPRESS = "wordpress"


class WordPressSourceRouter:
    """The `wordpress` alias is a read-only import source (docs/decisions.md §3).

    No model is stored there and no migration may run against it. Writes are
    additionally rejected by the database session itself (see settings).
    """

    def db_for_read(self, model: type, **hints: object) -> str:
        return "default"

    def db_for_write(self, model: type, **hints: object) -> str:
        return "default"

    def allow_migrate(self, db: str, app_label: str, **hints: object) -> bool | None:
        if db == WORDPRESS:
            return False
        return None
