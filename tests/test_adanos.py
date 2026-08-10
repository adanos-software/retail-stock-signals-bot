import io
import json
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime
from http.client import HTTPException, IncompleteRead
from urllib import error
from urllib.parse import parse_qs, urlparse

import pytest

from retail_signals.adanos import (
    MAX_RETRY_AFTER_SECONDS,
    AdanosApiError,
    AdanosClient,
    _retry_after_seconds,
)


def _http_error(status: int, headers=None) -> error.HTTPError:
    return error.HTTPError(
        "https://api.example.test/explain",
        status,
        "test error",
        headers or {},
        io.BytesIO(b'{"detail":"test error"}'),
    )


def test_get_explanation_returns_empty_string_for_not_found(monkeypatch):
    def fake_urlopen(request, timeout):  # noqa: ARG001
        raise _http_error(404)

    monkeypatch.setattr("retail_signals.adanos.request.urlopen", fake_urlopen)

    explanation = AdanosClient(api_key="test", retries=0).get_explanation("MISSING")

    assert explanation == ""


def test_get_explanation_raises_for_other_http_errors(monkeypatch):
    def fake_urlopen(request, timeout):  # noqa: ARG001
        raise _http_error(401)

    monkeypatch.setattr("retail_signals.adanos.request.urlopen", fake_urlopen)

    with pytest.raises(AdanosApiError, match="HTTP 401"):
        AdanosClient(api_key="test", retries=0).get_explanation("GME")


def test_get_trending_window_uses_explicit_dates_without_days(monkeypatch):
    requested_urls = []

    def fake_urlopen(api_request, timeout):  # noqa: ARG001
        requested_urls.append(api_request.full_url)
        return _Response([])

    monkeypatch.setattr("retail_signals.adanos.request.urlopen", fake_urlopen)

    rows = AdanosClient(api_key="test", retries=0).get_trending_window(
        window_start=date(2026, 8, 8),
        window_end=date(2026, 8, 8),
        limit=100,
        offset=0,
    )

    query = parse_qs(urlparse(requested_urls[0]).query)
    assert rows == []
    assert query == {
        "from": ["2026-08-08"],
        "to": ["2026-08-08"],
        "limit": ["100"],
        "offset": ["0"],
        "type": ["stock"],
    }
    assert "days" not in query


def test_get_trending_window_rejects_invalid_page_bounds():
    client = AdanosClient(api_key="test", retries=0)

    with pytest.raises(ValueError, match="limit"):
        client.get_trending_window(
            window_start=date(2026, 8, 8),
            window_end=date(2026, 8, 8),
            limit=101,
        )
    with pytest.raises(ValueError, match="offset"):
        client.get_trending_window(
            window_start=date(2026, 8, 8),
            window_end=date(2026, 8, 8),
            offset=-1,
        )


def test_get_trending_window_rejects_malformed_rows(monkeypatch):
    def fake_urlopen(api_request, timeout):  # noqa: ARG001
        return _Response([{"ticker": "GOOD"}, "corrupt-row"])

    monkeypatch.setattr("retail_signals.adanos.request.urlopen", fake_urlopen)

    with pytest.raises(AdanosApiError, match="row at index 1: str"):
        AdanosClient(api_key="test", retries=0).get_trending_window(
            window_start=date(2026, 8, 8),
            window_end=date(2026, 8, 8),
        )


def test_publisher_trending_rejects_malformed_rows(monkeypatch):
    def fake_urlopen(api_request, timeout):  # noqa: ARG001
        return _Response([{"ticker": "GOOD"}, "corrupt-row"])

    monkeypatch.setattr("retail_signals.adanos.request.urlopen", fake_urlopen)

    with pytest.raises(AdanosApiError, match="row at index 1: str"):
        AdanosClient(api_key="test", retries=0).get_trending(days=1)


def test_burst_rate_limit_respects_retry_after(monkeypatch):
    attempts = 0
    sleeps = []

    def fake_urlopen(api_request, timeout):  # noqa: ARG001
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise _http_error(429, {"Retry-After": "3"})
        return _Response([])

    monkeypatch.setattr("retail_signals.adanos.request.urlopen", fake_urlopen)
    monkeypatch.setattr("retail_signals.adanos.time.sleep", sleeps.append)

    rows = AdanosClient(api_key="test", retries=1).get_trending(days=1)

    assert rows == []
    assert attempts == 2
    assert sleeps == [3.0]


def test_retry_after_is_capped_and_supports_http_dates(monkeypatch):
    attempts = 0
    sleeps = []

    def fake_urlopen(api_request, timeout):  # noqa: ARG001
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise _http_error(429, {"Retry-After": "1e300"})
        return _Response([])

    monkeypatch.setattr("retail_signals.adanos.request.urlopen", fake_urlopen)
    monkeypatch.setattr("retail_signals.adanos.time.sleep", sleeps.append)

    AdanosClient(api_key="test", retries=1).get_trending(days=1)

    assert sleeps == [MAX_RETRY_AFTER_SECONDS]

    now = datetime(2026, 8, 9, 12, tzinfo=UTC)
    retry_at = format_datetime(now + timedelta(seconds=30), usegmt=True)
    assert _retry_after_seconds(retry_at, now_utc=now) == 30


def test_service_unavailable_respects_retry_after(monkeypatch):
    attempts = 0
    sleeps = []

    def fake_urlopen(api_request, timeout):  # noqa: ARG001
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise _http_error(503, {"Retry-After": "7"})
        return _Response([])

    monkeypatch.setattr("retail_signals.adanos.request.urlopen", fake_urlopen)
    monkeypatch.setattr("retail_signals.adanos.time.sleep", sleeps.append)

    assert AdanosClient(api_key="test", retries=1).get_trending(days=1) == []
    assert attempts == 2
    assert sleeps == [7.0]


def test_monthly_rate_limit_without_retry_after_stops_immediately(monkeypatch):
    attempts = 0
    sleeps = []

    def fake_urlopen(api_request, timeout):  # noqa: ARG001
        nonlocal attempts
        attempts += 1
        raise _http_error(429)

    monkeypatch.setattr("retail_signals.adanos.request.urlopen", fake_urlopen)
    monkeypatch.setattr("retail_signals.adanos.time.sleep", sleeps.append)

    with pytest.raises(AdanosApiError, match="HTTP 429"):
        AdanosClient(api_key="test", retries=3).get_trending(days=1)

    assert attempts == 1
    assert sleeps == []


def test_client_rejects_invalid_retry_settings():
    with pytest.raises(ValueError, match="timeout"):
        AdanosClient(api_key="test", timeout=float("nan"))
    with pytest.raises(ValueError, match="retries"):
        AdanosClient(api_key="test", retries=-1)


@pytest.mark.parametrize(
    ("field", "value"),
    (("timeout", True), ("timeout", "30"), ("retry_sleep", True)),
)
def test_client_rejects_non_numeric_or_boolean_timing_settings(field, value):
    with pytest.raises(ValueError):
        AdanosClient(api_key="test", **{field: value})


@pytest.mark.parametrize(
    "base_url",
    (
        "not-a-url",
        "ftp://api.example.test",
        "https://user:dummy@api.example.test",
        "https://api.example.test?token=dummy",
        "https://api.example.test#fragment",
        "https://api.example.test:invalid",
        "https://api.example.test/with space",
    ),
)
def test_client_rejects_invalid_or_credential_bearing_base_urls(base_url):
    with pytest.raises(ValueError, match="base URL"):
        AdanosClient(api_key="test", base_url=base_url)


@pytest.mark.parametrize(
    ("days", "limit"),
    ((0, 50), (True, 50), (1, 0), (1, 101), (1, True)),
)
def test_get_trending_rejects_invalid_window_settings(days, limit):
    with pytest.raises(ValueError):
        AdanosClient(api_key="test").get_trending(days=days, limit=limit)


def test_invalid_utf8_is_normalized_to_api_error(monkeypatch):
    monkeypatch.setattr(
        "retail_signals.adanos.request.urlopen",
        lambda api_request, timeout: _RawResponse(b"\xff"),  # noqa: ARG005
    )

    with pytest.raises(AdanosApiError, match="Adanos fetch failed"):
        AdanosClient(api_key="test", retries=0).get_trending(days=1)


def test_truncated_response_is_retried(monkeypatch):
    attempts = 0
    sleeps = []

    def fake_urlopen(api_request, timeout):  # noqa: ARG001
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return _ReadErrorResponse(IncompleteRead(b"[", 1))
        return _Response([])

    monkeypatch.setattr("retail_signals.adanos.request.urlopen", fake_urlopen)
    monkeypatch.setattr("retail_signals.adanos.time.sleep", sleeps.append)

    assert AdanosClient(api_key="test", retries=1).get_trending(days=1) == []
    assert attempts == 2
    assert sleeps == [1.0]


@pytest.mark.parametrize(
    "failure",
    (
        IncompleteRead(b"[", 1),
        HTTPException("truncated response"),
        OSError("connection reset while reading"),
    ),
)
def test_response_read_failure_exhaustion_is_normalized(monkeypatch, failure):
    attempts = 0
    sleeps = []

    def fake_urlopen(api_request, timeout):
        nonlocal attempts
        attempts += 1
        return _ReadErrorResponse(failure)

    monkeypatch.setattr("retail_signals.adanos.request.urlopen", fake_urlopen)
    monkeypatch.setattr("retail_signals.adanos.time.sleep", sleeps.append)

    with pytest.raises(AdanosApiError, match="Adanos fetch failed") as exc_info:
        AdanosClient(api_key="test", retries=1).get_trending(days=1)

    assert attempts == 2
    assert sleeps == [1.0]
    assert exc_info.value.__cause__ is failure


def test_truncated_http_error_body_still_uses_status_retry_policy(monkeypatch):
    attempts = 0

    def fake_urlopen(api_request, timeout):  # noqa: ARG001
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise error.HTTPError(
                "https://api.example.test",
                503,
                "test error",
                {},
                _ReadErrorResponse(IncompleteRead(b"[", 1)),
            )
        return _Response([])

    monkeypatch.setattr("retail_signals.adanos.request.urlopen", fake_urlopen)
    monkeypatch.setattr("retail_signals.adanos.time.sleep", lambda delay: None)

    assert AdanosClient(api_key="test", retries=1).get_trending(days=1) == []
    assert attempts == 2


def test_http_error_redacts_api_key(monkeypatch):
    sentinel = "response-marker-123"

    def fake_urlopen(api_request, timeout):  # noqa: ARG001
        raise error.HTTPError(
            "https://api.example.test",
            500,
            "test error",
            {},
            io.BytesIO(f'{{"detail":"{sentinel}"}}'.encode()),
        )

    monkeypatch.setattr("retail_signals.adanos.request.urlopen", fake_urlopen)

    with pytest.raises(AdanosApiError) as exc_info:
        AdanosClient(api_key=sentinel, retries=0).get_trending(days=1)

    assert sentinel not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class _RawResponse(_Response):
    def read(self):
        return self.payload


class _ReadErrorResponse(_Response):
    def read(self):
        raise self.payload

    def close(self):
        return None
