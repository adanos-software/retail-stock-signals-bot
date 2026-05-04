from retail_signals.signals import select_daily_signals, tickers_requiring_explanations


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
