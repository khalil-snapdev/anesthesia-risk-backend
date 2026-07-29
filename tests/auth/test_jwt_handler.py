from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.auth.jwt_handler import create_access_token, decode_access_token
from app.config import settings
from app.exceptions import AppException


class TestCreateAndDecodeRoundTrip:
    def test_round_trips_user_id_and_role(self) -> None:
        token = create_access_token(user_id="user-123", role="nurse")
        payload = decode_access_token(token)

        assert payload.user_id == "user-123"
        assert payload.role == "nurse"

    def test_role_none_round_trips_as_none(self) -> None:
        token = create_access_token(user_id="user-456", role=None)
        payload = decode_access_token(token)

        assert payload.user_id == "user-456"
        assert payload.role is None

    def test_token_is_a_string(self) -> None:
        token = create_access_token(user_id="user-789", role="surgeon")
        assert isinstance(token, str)
        assert len(token) > 0


class TestDecodeAccessTokenRejectsBadTokens:
    def test_garbage_string_raises_401(self) -> None:
        with pytest.raises(AppException) as exc_info:
            decode_access_token("not-a-real-token")
        assert exc_info.value.status_code == 401

    def test_expired_token_raises_401(self) -> None:
        now = datetime.now(UTC)
        expired_payload = {
            "sub": "user-123",
            "role": "nurse",
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
        }
        expired_token = jwt.encode(expired_payload, settings.JWT_SECRET_KEY, algorithm="HS256")

        with pytest.raises(AppException) as exc_info:
            decode_access_token(expired_token)
        assert exc_info.value.status_code == 401

    def test_tampered_signature_raises_401(self) -> None:
        token = create_access_token(user_id="user-123", role="nurse")
        last_char = token[-1]
        replacement = "x" if last_char != "x" else "y"
        tampered = token[:-1] + replacement

        with pytest.raises(AppException) as exc_info:
            decode_access_token(tampered)
        assert exc_info.value.status_code == 401

    def test_token_signed_with_wrong_secret_raises_401(self) -> None:
        payload = {
            "sub": "user-123",
            "role": "nurse",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
        }
        token = jwt.encode(payload, "a-completely-different-secret-key-value", algorithm="HS256")

        with pytest.raises(AppException) as exc_info:
            decode_access_token(token)
        assert exc_info.value.status_code == 401

    def test_token_missing_subject_claim_raises_401(self) -> None:
        payload = {
            "role": "nurse",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
        }
        token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")

        with pytest.raises(AppException) as exc_info:
            decode_access_token(token)
        assert exc_info.value.status_code == 401
