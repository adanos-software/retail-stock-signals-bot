"""Client for the Adanos Reddit stock sentiment API."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request


DEFAULT_BASE_URL = "https://api.adanos.org"


class AdanosApiError(RuntimeError):
    """Raised when Adanos data cannot be fetched."""


@dataclass(frozen=True)
class AdanosClient:
    """Small urllib-based client to keep the bot dependency-light."""

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    timeout: float = 30.0
    retries: int = 2
    retry_sleep: float = 1.0

    def get_trending(self, *, days: int, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch stock-only Reddit trending rows."""
        payload = self._load_json(
            "/reddit/stocks/v1/trending",
            {"days": days, "limit": limit, "type": "stock"},
        )
        if not isinstance(payload, list):
            raise AdanosApiError(f"Unexpected trending payload: {type(payload).__name__}")
        return [row for row in payload if isinstance(row, dict)]

    def get_explanation(self, ticker: str) -> str:
        """Fetch one ticker explanation, returning an empty string when absent."""
        payload = self._load_json(f"/reddit/stocks/v1/stock/{parse.quote(ticker)}/explain", {})
        if not isinstance(payload, dict):
            return ""
        explanation = payload.get("explanation")
        return explanation.strip() if isinstance(explanation, str) else ""

    def _load_json(self, path: str, params: dict[str, Any]) -> Any:
        url = self._build_url(path, params)
        headers = {
            "Accept": "application/json",
            "User-Agent": "retail-stock-signals-bot/0.1",
            "X-API-Key": self.api_key,
        }
        last_error: Exception | None = None

        for attempt in range(self.retries + 1):
            try:
                api_request = request.Request(url, headers=headers)
                with request.urlopen(api_request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                last_error = AdanosApiError(f"HTTP {exc.code} from {path}: {body[:300]}")
                if exc.code not in {429, 500, 502, 503, 504}:
                    break
            except (TimeoutError, error.URLError, json.JSONDecodeError) as exc:
                last_error = exc

            if attempt < self.retries:
                time.sleep(self.retry_sleep * (attempt + 1))

        raise AdanosApiError(f"Adanos fetch failed for {path}: {last_error}") from last_error

    def _build_url(self, path: str, params: dict[str, Any]) -> str:
        clean_base = self.base_url.rstrip("/")
        query = parse.urlencode(params)
        return f"{clean_base}{path}?{query}" if query else f"{clean_base}{path}"
