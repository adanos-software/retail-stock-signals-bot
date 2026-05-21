import json
from urllib import error

import pytest

from retail_signals.deepseek import (
    DeepSeekClient,
    DeepSeekError,
    _loads_json_object,
    _prompt_payload,
    _replace_trading_framing,
    _style_profile,
)
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


def test_loads_json_object_tolerates_markdown_fence():
    decoded = _loads_json_object(
        """```json
        {"intro": "a", "takeaway": "b", "question": "c"}
        ```"""
    )

    assert decoded == {"intro": "a", "takeaway": "b", "question": "c"}


def test_deepseek_accepts_valid_takeaway(monkeypatch):
    def fake_urlopen(request, timeout):  # noqa: ARG001
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "takeaway": "takeaway text",
                                    "signal_reads": {
                                        "top_buzz": "top read",
                                        "cleanest_breakout": "clean read",
                                        "biggest_breakout": "breakout read",
                                        "biggest_fade": "fade read",
                                    },
                                }
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("retail_signals.deepseek.request.urlopen", fake_urlopen)

    copy = DeepSeekClient(api_key="test").generate_copy(_signals())

    assert copy.takeaway == "takeaway text"
    assert copy.signal_reads["top_buzz"] == "top read"


def test_prompt_payload_includes_professional_style_guardrails():
    payload = _prompt_payload(_signals())

    assert payload["style"]["name"] in {"market_desk", "signal_brief", "flow_context"}
    assert "hard_facts" in payload
    assert "allowed_interpretations" in payload
    assert payload["unverified_context"] == {}
    assert "signals" not in payload
    assert any("professional market desk note" in item for item in payload["constraints"])
    assert any("Do not state causal claims as fact" in item for item in payload["constraints"])
    assert any("unverified_context" in item for item in payload["constraints"])
    assert any("avoid generic AI phrasing" in item for item in payload["constraints"])
    assert "today's signal" in " ".join(payload["constraints"])
    assert "signal_reads" in payload["output_schema"]


def test_prompt_payload_includes_explain_context_when_available():
    signals = select_daily_signals(
        date_label="May 20, 2026",
        trending_today=[
            _row("NVDA", 82.6, 0.01, 26, 21, [80, 82.6]),
            _row("GRPN", 67.0, 0.148, 36, 11, [55.6, 67.0]),
        ],
        trending_7d=[
            _row("NVDA", 82.6, 0.01, 26, 21, [80, 82.6]),
            _row("GRPN", 67.0, 0.148, 36, 11, [55.6, 67.0]),
        ],
        explanations={"NVDA": "NVDA is trending because demand is rising around agentic AI."},
    )

    payload = _prompt_payload(signals)

    assert payload["unverified_context"] == {
        "NVDA": "Reddit discussion points to demand is rising around agentic AI."
    }
    assert payload["hard_facts"]["selected"]["top_buzz"]["reddit_context"].startswith(
        "Reddit discussion points to"
    )


def test_style_profile_rotates_by_date_label():
    profiles = {_style_profile(label)["name"] for label in ["May 4, 2026", "May 5, 2026", "May 6, 2026"]}

    assert len(profiles) > 1


def test_replace_trading_framing_removes_trade_call_phrases():
    text = _replace_trading_framing(
        "Which has more staying power: the M&A play, acquisition play, or squeeze setup?"
    )

    assert text == (
        "Which has more staying power: the M&A narrative, "
        "acquisition narrative, or squeeze narrative?"
    )


def test_deepseek_softens_causal_claim_language(monkeypatch):
    def fake_urlopen(request, timeout):  # noqa: ARG001
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "takeaway": "GOOGL leads because attention is tied to AI demand.",
                                }
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("retail_signals.deepseek.request.urlopen", fake_urlopen)

    copy = DeepSeekClient(api_key="test").generate_copy(_signals())

    assert copy.takeaway == "GOOGL leads as attention is tied to AI demand."


def test_deepseek_rejects_internal_filtering_language(monkeypatch):
    def fake_urlopen(request, timeout):  # noqa: ARG001
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "takeaway": "After filtering an ambiguous ticker, the cleaned list looks better.",
                                }
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("retail_signals.deepseek.request.urlopen", fake_urlopen)

    with pytest.raises(DeepSeekError, match="no usable copy"):
        DeepSeekClient(api_key="test").generate_copy(_signals())


def test_deepseek_keeps_valid_signal_reads_when_takeaway_is_rejected(monkeypatch):
    def fake_urlopen(request, timeout):  # noqa: ARG001
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "takeaway": "After filtering an ambiguous ticker, the cleaned list looks better.",
                                    "signal_reads": {
                                        "top_buzz": "NVDA leads attention because AI demand is the main Reddit context.",
                                        "cleanest_breakout": "After filtering, this should be rejected.",
                                        "biggest_breakout": "WDC shows stronger buzz tied to AI memory demand.",
                                    },
                                }
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("retail_signals.deepseek.request.urlopen", fake_urlopen)

    copy = DeepSeekClient(api_key="test").generate_copy(_signals())

    assert copy.takeaway == ""
    assert copy.signal_reads == {
        "top_buzz": "NVDA leads attention as AI demand is the main Reddit context.",
        "biggest_breakout": "WDC shows stronger buzz tied to AI memory demand.",
    }


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
