from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.db.models import QuerySet
from django.http import HttpRequest

from accounts.models import User
from accounts.tokens import revoke_all_sessions


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Operators change roles (groups), deactivate users and revoke sessions
    here (docs/decisions.md §7)."""

    list_display = (
        "username",
        "email",
        "wp_user_id",
        "is_active",
        "is_staff",
        "group_names",
    )
    readonly_fields = ("wp_user_id",)
    fieldsets = (
        *BaseUserAdmin.fieldsets,
        ("WordPress", {"fields": ("wp_user_id",)}),
    )
    actions = ["revoke_sessions"]

    @admin.display(description="Roles")
    def group_names(self, user: User) -> str:
        return ", ".join(sorted(group.name for group in user.groups.all()))

    def get_queryset(self, request: HttpRequest) -> QuerySet[User]:
        return super().get_queryset(request).prefetch_related("groups")

    @admin.action(
        description="Revoke all sessions (refresh tokens)", permissions=["change"]
    )
    def revoke_sessions(self, request: HttpRequest, users: QuerySet[User]) -> None:
        revoked = sum(revoke_all_sessions(user) for user in users)
        self.message_user(
            request,
            f"Revoked {revoked} refresh token(s). Access tokens already issued "
            "stay valid until they expire (at most 5 minutes).",
            messages.SUCCESS,
        )
