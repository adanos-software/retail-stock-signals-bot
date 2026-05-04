import json
from urllib import error

import pytest

from retail_signals.deepseek import DeepSeekClient, DeepSeekError
from retail_signals.signals import select_daily_signals


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_deepseek_rejects_invalid_json(monkeypatch):
    def fake_urlopen(request, timeout):  # noqa: ARG001
        return _FakeResponse({"choices": [{"message": {"content": "not json"}}]})

    monkeypatch.setattr("retail_signals.deepseek.request.urlopen", fake_urlopen)

    with pytest.raises(DeepSeekError):
        DeepSeekClient(api_key="test").generate_copy(_signals())


def test_deepseek_reports_http_error(monkeypatch):
    def fake_urlopen(request, timeout):  # noqa: ARG001
        raise error.HTTPError("https://api.example.test", 401, "Unauthorized", None, _Body())

    monkeypatch.setattr("retail_signals.deepseek.request.urlopen", fake_urlopen)

    with pytest.raises(DeepSeekError, match="HTTP 401"):
        DeepSeekClient(api_key="test", retries=0).generate_copy(_signals())


class _Body:
    def read(self):
        return b'{"error":"bad key"}'

    def close(self):
        return None


def _signals():
    rows = [
        _row("GME", 82.2, 0.007, 28, 28, [79.8, 82.2]),
        _row("XRX", 72.3, 0.161, 50, 16, [20.8, 71.0]),
        _row("POET", 62.5, -0.045, 25, 36, [71.5, 62.5], trend="falling"),
    ]
    return select_daily_signals(
        date_label="May 4, 2026",
        trending_today=rows,
        trending_7d=rows,
    )


def _row(ticker, buzz, sentiment, bullish, bearish, history, trend="rising"):
    return {
        "ticker": ticker,
        "company_name": f"{ticker} Inc",
        "buzz_score": buzz,
        "sentiment_score": sentiment,
        "bullish_pct": bullish,
        "bearish_pct": bearish,
        "subreddit_count": 10,
        "trend": trend,
        "trend_history": history,
    }
