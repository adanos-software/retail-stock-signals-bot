import pytest

from retail_signals.signals import (
    resolve_shared_narrative_explanations,
    sanitize_explanation,
    select_daily_signals,
    tickers_requiring_explanations,
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


def test_select_daily_signals_prefers_buzz_and_quality_breakout():
    today = [
        _row("AAA", 70.0, 0.01, 30, 30, [60, 70]),
        _row("TOP", 82.0, 0.00, 28, 28, [80, 82]),
    ]
    seven_day = [
        _row("BIG", 74.0, 0.04, 40, 20, [0, 74]),
        _row("CLEAN", 71.0, 0.18, 51, 13, [20, 71]),
        _row("FADE", 62.0, -0.05, 25, 36, [71, 62], trend="falling"),
    ]

    signals = select_daily_signals(
        date_label="May 4, 2026",
        trending_today=today,
        trending_7d=seven_day,
    )

    assert signals.top_buzz.ticker == "TOP"
    assert signals.biggest_breakout.ticker == "BIG"
    assert signals.cleanest_breakout.ticker == "CLEAN"
    assert signals.biggest_fade.ticker == "FADE"


def test_select_daily_signals_falls_back_to_biggest_gainer_when_no_quality_candidate():
    today = [_row("TOP", 82.0, 0.00, 28, 28, [80, 82])]
    seven_day = [
        _row("BIG", 74.0, -0.04, 20, 40, [0, 74]),
        _row("LOW", 55.0, 0.20, 60, 10, [20, 55]),
    ]

    signals = select_daily_signals(
        date_label="May 4, 2026",
        trending_today=today,
        trending_7d=seven_day,
    )

    assert signals.biggest_breakout.ticker == "BIG"
    assert signals.cleanest_breakout.ticker == "BIG"


def test_select_daily_signals_rejects_missing_7d_history():
    rows = [_row("GME", 82.0, 0.0, 28, 28, [])]

    with pytest.raises(ValueError, match="trending_7d rows must include trend_history"):
        select_daily_signals(
            date_label="May 4, 2026",
            trending_today=rows,
            trending_7d=rows,
        )


def test_select_daily_signals_filters_numeric_tickers():
    today = [
        _row("7974", 90.0, 0.04, 31, 22, [91, 90]),
        _row("NVDA", 82.0, 0.05, 35, 18, [80, 82]),
    ]
    seven_day = [
        _row("7974", 90.0, 0.04, 31, 22, [95, 90]),
        _row("BABA", 68.0, 0.05, 35, 18, [30, 68]),
        _row("NKE", 61.0, -0.02, 20, 22, [66, 61], trend="falling"),
    ]

    signals = select_daily_signals(
        date_label="May 14, 2026",
        trending_today=today,
        trending_7d=seven_day,
    )

    selected = [
        signals.top_buzz.ticker,
        signals.biggest_breakout.ticker,
        signals.biggest_fade.ticker,
        *[signal.ticker for signal in signals.movers],
    ]
    assert "7974" not in selected
    assert signals.top_buzz.ticker == "NVDA"
    assert signals.biggest_breakout.ticker == "BABA"


def test_select_daily_signals_deduplicates_movers():
    rows = [
        _row("AAA", 80.0, 0.05, 35, 20, [70, 80]),
        _row("BBB", 70.0, 0.02, 25, 20, [75, 70], trend="falling"),
    ]

    signals = select_daily_signals(
        date_label="May 14, 2026",
        trending_today=rows,
        trending_7d=rows,
    )

    mover_tickers = [signal.ticker for signal in signals.movers]
    assert mover_tickers == ["AAA", "BBB"]


def test_tickers_requiring_explanations_are_unique_and_ordered():
    rows = [
        _row("GME", 82, 0, 28, 28, [80, 82]),
        _row("XRX", 72, 0.18, 51, 13, [20, 72]),
        _row("POET", 62, -0.05, 25, 36, [71, 62]),
    ]
    signals = select_daily_signals(
        date_label="May 4, 2026",
        trending_today=rows,
        trending_7d=rows,
    )

    assert tickers_requiring_explanations(signals) == ["GME", "XRX", "POET"]


def test_resolve_shared_narrative_replaces_generic_target_explanation():
    today = [
        _row("GME", 82.0, 0.0, 28, 28, [80, 82]),
        _row("EBAY", 76.0, 0.05, 41, 20, [0, 74]),
        _row("POET", 62.0, -0.05, 25, 36, [71, 62], trend="falling"),
    ]
    signals = select_daily_signals(
        date_label="May 4, 2026",
        trending_today=today,
        trending_7d=today,
    )

    resolved = resolve_shared_narrative_explanations(
        signals,
        {
            "GME": "GME is trending because GameStop and eBay are being discussed together.",
            "EBAY": "EBAY shows mixed sentiment without a clear catalyst.",
        },
    )

    assert resolved["EBAY"].startswith("EBAY appears tied to the same GME/EBAY narrative")
    assert "GameStop and eBay are being discussed together" in resolved["EBAY"]


def test_sanitize_explanation_reframes_safe_context_and_drops_unsafe_claims():
    assert sanitize_explanation(
        "GME",
        "GME is trending because GameStop and eBay are being discussed together.",
    ) == "Reddit discussion points to GameStop and eBay are being discussed together."
    assert sanitize_explanation("GOOGL", "GOOGL is trending because Google passed Nvidia.") == ""
    assert sanitize_explanation(
        "JPM",
        "JPM is trending because a settlement was rejected.",
    ) == "Reddit discussion points to a settlement was rejected."
    assert sanitize_explanation("EBAY", "EBAY shows mixed sentiment without a clear catalyst.") == ""


def test_sanitize_explanation_removes_trading_call_language():
    assert sanitize_explanation(
        "GRPN",
        "GRPN is trending because low float and major short interest are creating a sharp buying opportunity.",
    ) == (
        "Reddit discussion points to low float, major short interest, and "
        "short-squeeze discussion."
    )
