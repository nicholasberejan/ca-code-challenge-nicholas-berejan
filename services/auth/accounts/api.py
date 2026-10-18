"""Token endpoints: login, refresh, logout (docs/decisions.md §7)."""

from django.contrib.auth import authenticate
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.tokens import TokenRejected, issue_tokens, revoke, rotate


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(trim_whitespace=False)


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


def _invalid(message: str) -> Response:
    return Response({"detail": message}, status=status.HTTP_401_UNAUTHORIZED)


class LoginView(APIView):
    """POST {"username", "password"} -> {"access", "refresh"}."""

    def post(self, request: Request) -> Response:
        data = LoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        # Django's backend refuses inactive users and upgrades a migrated
        # WordPress hash to the default hasher on success.
        user = authenticate(
            request,
            username=data.validated_data["username"],
            password=data.validated_data["password"],
        )
        if user is None:
            return _invalid("No active account found with these credentials.")
        pair = issue_tokens(user)
        return Response({"access": pair.access, "refresh": pair.refresh})


class RefreshView(APIView):
    """POST {"refresh"} -> a new {"access", "refresh"}; the old refresh token
    is used up."""

    def post(self, request: Request) -> Response:
        data = RefreshSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            pair = rotate(data.validated_data["refresh"])
        except TokenRejected:
            return _invalid("Refresh token is invalid, expired or already used.")
        return Response({"access": pair.access, "refresh": pair.refresh})


class LogoutView(APIView):
    """POST {"refresh"}: that refresh token can no longer be used. Access
    tokens already issued remain valid until they expire."""

    def post(self, request: Request) -> Response:
        data = RefreshSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            revoke(data.validated_data["refresh"])
        except TokenRejected:
            return _invalid("Refresh token is invalid, expired or already used.")
        return Response(status=status.HTTP_204_NO_CONTENT)
