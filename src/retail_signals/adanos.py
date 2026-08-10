"""Client for the Adanos Reddit stock sentiment API."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from typing import Any
from urllib import error, parse, request

from retail_signals import __version__

DEFAULT_BASE_URL = "https://api.adanos.org"
MAX_RETRY_AFTER_SECONDS = 60.0


class AdanosApiError(RuntimeError):
    """Raised when Adanos data cannot be fetched."""


def parse_timeout(value: str) -> float:
    """Parse one positive finite CLI timeout."""
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError("timeout must be a positive finite number")
    return parsed


def parse_retries(value: str) -> int:
    """Parse one nonnegative CLI retry count."""
    parsed = int(value)
    if parsed < 0:
        raise ValueError("retries must not be negative")
    return parsed


def parse_trending_limit(value: str) -> int:
    """Parse one API page size accepted by the trending endpoints."""
    parsed = int(value)
    if not 1 <= parsed <= 100:
        raise ValueError("limit must be in [1, 100]")
    return parsed


def validate_base_url(value: str) -> str:
    """Reject malformed or credential-bearing API base URLs."""
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise ValueError("base URL must be a valid HTTP(S) URL")
    try:
        parsed = parse.urlsplit(value)
        hostname = parsed.hostname
        _port = parsed.port
    except ValueError as exc:
        raise ValueError("base URL must be a valid HTTP(S) URL") from exc
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ValueError("base URL must be a valid HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("base URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("base URL must not contain a query or fragment")
    return value.rstrip("/")


@dataclass(frozen=True)
class AdanosClient:
    """Small urllib-based client to keep the bot dependency-light."""

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    timeout: float = 30.0
    retries: int = 2
    retry_sleep: float = 1.0

    def __post_init__(self) -> None:
        validate_base_url(self.base_url)
        if (
            isinstance(self.timeout, bool)
            or not isinstance(self.timeout, (int, float))
            or not math.isfinite(self.timeout)
            or self.timeout <= 0
        ):
            raise ValueError("timeout must be a positive finite number")
        if isinstance(self.retries, bool) or not isinstance(self.retries, int):
            raise ValueError("retries must be an integer")
        if self.retries < 0:
            raise ValueError("retries must not be negative")
        if (
            isinstance(self.retry_sleep, bool)
            or not isinstance(self.retry_sleep, (int, float))
            or not math.isfinite(self.retry_sleep)
            or self.retry_sleep < 0
        ):
            raise ValueError("retry_sleep must be a nonnegative finite number")

    def get_trending(self, *, days: int, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch stock-only Reddit trending rows."""
        if isinstance(days, bool) or not isinstance(days, int) or days < 1:
            raise ValueError("days must be a positive integer")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise ValueError("limit must be an integer in [1, 100]")
        payload = self._load_json(
            "/reddit/stocks/v1/trending",
            {"days": days, "limit": limit, "type": "stock"},
        )
        if not isinstance(payload, list):
            raise AdanosApiError(
                f"Unexpected trending payload: {type(payload).__name__}"
            )
        invalid_index = next(
            (index for index, row in enumerate(payload) if not isinstance(row, dict)),
            None,
        )
        if invalid_index is not None:
            raise AdanosApiError(
                f"Unexpected trending row at index {invalid_index}: "
                f"{type(payload[invalid_index]).__name__}"
            )
        return payload

    def get_trending_window(
        self,
        *,
        window_start: date,
        window_end: date,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Fetch an explicit closed UTC window for point-in-time capture."""
        if window_start > window_end:
            raise ValueError("window_start must be on or before window_end")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise ValueError("limit must be an integer in [1, 100]")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a nonnegative integer")
        payload = self._load_json(
            "/reddit/stocks/v1/trending",
            {
                "from": window_start.isoformat(),
                "to": window_end.isoformat(),
                "limit": limit,
                "offset": offset,
                "type": "stock",
            },
        )
        if not isinstance(payload, list):
            raise AdanosApiError(
                f"Unexpected trending payload: {type(payload).__name__}"
            )
        invalid_index = next(
            (index for index, row in enumerate(payload) if not isinstance(row, dict)),
            None,
        )
        if invalid_index is not None:
            raise AdanosApiError(
                f"Unexpected trending row at index {invalid_index}: "
                f"{type(payload[invalid_index]).__name__}"
            )
        return payload

    def get_explanation(self, ticker: str) -> str:
        """Fetch one ticker explanation, returning an empty string when absent."""
        payload = self._load_json(
            f"/reddit/stocks/v1/stock/{parse.quote(ticker)}/explain",
            {},
            return_none_on_404=True,
        )
        if not isinstance(payload, dict):
            return ""
        explanation = payload.get("explanation")
        return explanation.strip() if isinstance(explanation, str) else ""

    def _load_json(
        self,
        path: str,
        params: dict[str, Any],
        *,
        return_none_on_404: bool = False,
    ) -> Any:
        url = self._build_url(path, params)
        headers = {
            "Accept": "application/json",
            "User-Agent": f"retail-stock-signals-bot/{__version__}",
            "X-API-Key": self.api_key,
        }
        last_error: Exception | None = None

        for attempt in range(self.retries + 1):
            retry_delay: float | None = None
            try:
                api_request = request.Request(url, headers=headers)
                with request.urlopen(api_request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except error.HTTPError as exc:
                if exc.code == 404 and return_none_on_404:
                    exc.close()
                    return None
                retry_after = (
                    exc.headers.get("Retry-After") if exc.headers is not None else None
                )
                try:
                    try:
                        body = exc.read().decode("utf-8", errors="replace")
                    except (HTTPException, OSError) as body_error:
                        body = (
                            f"<response body unavailable: {type(body_error).__name__}>"
                        )
                finally:
                    exc.close()
                if self.api_key:
                    body = body.replace(self.api_key, "[REDACTED]")
                last_error = AdanosApiError(
                    f"HTTP {exc.code} from {path}: {body[:300]}"
                )
                if exc.code == 429 and retry_after is None:
                    break
                if exc.code not in {429, 500, 502, 503, 504}:
                    break
                if retry_after is not None:
                    retry_delay = _retry_after_seconds(retry_after)
            except (HTTPException, OSError, UnicodeError, ValueError) as exc:
                last_error = exc

            if attempt < self.retries:
                delay = (
                    retry_delay
                    if retry_delay is not None
                    else self.retry_sleep * (attempt + 1)
                )
                time.sleep(delay)

        raise AdanosApiError(
            f"Adanos fetch failed for {path}: {last_error}"
        ) from last_error

    def _build_url(self, path: str, params: dict[str, Any]) -> str:
        clean_base = self.base_url.rstrip("/")
        query = parse.urlencode(params)
        return f"{clean_base}{path}?{query}" if query else f"{clean_base}{path}"


def _retry_after_seconds(
    value: str,
    *,
    now_utc: datetime | None = None,
) -> float | None:
    try:
        seconds = float(value)
    except (TypeError, ValueError, OverflowError):
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        reference = now_utc or datetime.now(UTC)
        if reference.tzinfo is None:
            raise ValueError("now_utc must be timezone-aware")
        seconds = (retry_at.astimezone(UTC) - reference.astimezone(UTC)).total_seconds()
    if not math.isfinite(seconds):
        return None
    return min(max(seconds, 0.0), MAX_RETRY_AFTER_SECONDS)
