from typing import Any

import pytest
from google.auth import exceptions as google_exceptions

from app.auth.google_oauth import GoogleUserInfo, verify_google_token
from app.exceptions import AppException

_PATCH_TARGET = "app.auth.google_oauth.google_id_token.verify_oauth2_token"


def _mock_verify_returning(monkeypatch: pytest.MonkeyPatch, claims: dict[str, Any]) -> None:
    def _fake_verify_oauth2_token(id_token: str, request: Any, audience: str) -> dict[str, Any]:
        return claims

    monkeypatch.setattr(_PATCH_TARGET, _fake_verify_oauth2_token)


def _mock_verify_raising(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    def _fake_verify_oauth2_token(id_token: str, request: Any, audience: str) -> dict[str, Any]:
        raise exc

    monkeypatch.setattr(_PATCH_TARGET, _fake_verify_oauth2_token)


class TestVerifyGoogleTokenValid:
    def test_returns_verified_identity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_verify_returning(
            monkeypatch,
            {
                "sub": "1234567890",
                "email": "jane.doe@example.com",
                "name": "Jane Doe",
            },
        )

        info = verify_google_token("a-fake-but-well-formed-token")

        assert info == GoogleUserInfo(
            google_sub_id="1234567890",
            email="jane.doe@example.com",
            full_name="Jane Doe",
        )

    def test_missing_name_claim_defaults_to_empty_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_verify_returning(
            monkeypatch,
            {"sub": "1234567890", "email": "jane.doe@example.com"},
        )

        info = verify_google_token("a-fake-but-well-formed-token")

        assert info.full_name == ""


class TestVerifyGoogleTokenInvalid:
    def test_invalid_or_expired_token_raises_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_verify_raising(monkeypatch, ValueError("Token expired"))

        with pytest.raises(AppException) as exc_info:
            verify_google_token("an-expired-token")
        assert exc_info.value.status_code == 401

    def test_tampered_token_raises_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        error = google_exceptions.GoogleAuthError("Wrong issuer")  # type: ignore[no-untyped-call]
        _mock_verify_raising(monkeypatch, error)

        with pytest.raises(AppException) as exc_info:
            verify_google_token("a-tampered-token")
        assert exc_info.value.status_code == 401

    def test_error_message_never_leaks_internal_detail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_verify_raising(monkeypatch, ValueError("some internal google-auth detail"))

        with pytest.raises(AppException) as exc_info:
            verify_google_token("a-bad-token")
        assert "internal" not in exc_info.value.message.lower()

    def test_claims_missing_sub_raises_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_verify_returning(monkeypatch, {"email": "jane.doe@example.com"})

        with pytest.raises(AppException) as exc_info:
            verify_google_token("a-fake-but-well-formed-token")
        assert exc_info.value.status_code == 401

    def test_claims_missing_email_raises_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_verify_returning(monkeypatch, {"sub": "1234567890"})

        with pytest.raises(AppException) as exc_info:
            verify_google_token("a-fake-but-well-formed-token")
        assert exc_info.value.status_code == 401
