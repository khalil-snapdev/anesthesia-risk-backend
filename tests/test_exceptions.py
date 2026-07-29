from app.exceptions import AppException


def test_app_exception_defaults_to_status_500() -> None:
    exc = AppException("something broke")

    assert exc.message == "something broke"
    assert exc.status_code == 500


def test_app_exception_accepts_custom_status_code() -> None:
    exc = AppException("not found", status_code=404)

    assert exc.message == "not found"
    assert exc.status_code == 404
