from retail_signals.render import render_post, render_title
from retail_signals.signals import select_daily_signals


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


def test_render_post_uses_mobile_first_sections_and_explanations():
    rows = [
        _row("GME", 82.2, 0.007, 28, 28, [79.8, 82.2]),
        _row("XRX", 72.3, 0.161, 50, 16, [20.8, 71.0]),
        _row("POET", 62.5, -0.045, 25, 36, [71.5, 62.5], trend="falling"),
    ]
    signals = select_daily_signals(
        date_label="May 4, 2026",
        trending_today=rows,
        trending_7d=rows,
        explanations={"GME": "GME is moving on a shared eBay narrative."},
    )

    post = render_post(signals)

    assert "### Signal Summary" in post
    assert "### 7-Day Movers" in post
    assert "| Ticker |" not in post
    assert "GME is moving on a shared eBay narrative." in post
    assert "Data-driven sentiment signal, not financial advice." in post


def test_render_post_adds_data_only_signal_interpretations():
    rows = [
        _row("GOOGL", 82.9, 0.05, 37, 16, [84, 82.9], trend="falling"),
        _row("CHWY", 62.8, 0.16, 45, 11, [41.9, 62.8]),
        _row("JPM", 74.2, -0.067, 22, 39, [78.8, 74.2], trend="falling"),
    ]
    signals = select_daily_signals(
        date_label="May 7, 2026",
        trending_today=rows,
        trending_7d=rows,
    )

    post = render_post(signals)

    assert "sustained attention rather than fresh acceleration" in post
    assert "bullish discussion stayed clearly above bearish discussion" in post
    assert "clearest caution signal" in post


def test_render_title_mentions_core_picks():
    rows = [
        _row("GME", 82.2, 0.007, 28, 28, [79.8, 82.2]),
        _row("XRX", 72.3, 0.161, 50, 16, [20.8, 71.0]),
        _row("POET", 62.5, -0.045, 25, 36, [71.5, 62.5], trend="falling"),
    ]
    signals = select_daily_signals(
        date_label="May 4, 2026",
        trending_today=rows,
        trending_7d=rows,
    )

    assert render_title(signals) == (
        "Daily Retail Stock Signals - May 4, 2026: "
        "GME Leads Buzz, XRX Sentiment Improves, XRX Moves Most"
    )


def test_render_title_does_not_overstate_negative_fade():
    rows = [
        _row("GOOGL", 82.9, 0.05, 37, 16, [84, 82.9], trend="falling"),
        _row("CHWY", 62.8, 0.16, 45, 11, [41.9, 62.8]),
        _row("BLK", 65.3, 0.068, 29, 15, [39.4, 65.3]),
        _row("JPM", 74.2, -0.067, 22, 39, [78.8, 74.2], trend="falling"),
    ]
    signals = select_daily_signals(
        date_label="May 7, 2026",
        trending_today=rows,
        trending_7d=rows,
    )

    title = render_title(signals)

    assert "JPM Fades" not in title
    assert title.endswith("BLK Moves Most")
