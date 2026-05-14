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


def test_render_post_uses_mobile_first_sections_without_raw_explanations():
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
    assert "**Top Buzz: GME**" in post
    assert "Buzz **82.2** | Sentiment **neutral** | Bull/Bear **28% / 28%**" in post
    assert "| Ticker |" not in post
    assert "GME is moving on a shared eBay narrative." not in post
    assert "Data-driven sentiment signal, not financial advice." in post


def test_render_post_adds_contrast_first_intro_and_data_only_reads():
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

    assert post.splitlines()[2] == (
        "Today's split: **GOOGL** led raw buzz, but **CHWY** had the cleaner sentiment profile."
    )
    assert "High absolute attention" in post
    assert "bullish discussion stayed clearly ahead of bearish discussion" in post
    assert "Attention cooled while sentiment was negative" in post
    assert "cleaned" not in post.lower()
    assert "filter" not in post.lower()
    assert "ambiguous" not in post.lower()


def test_render_title_is_seo_safe_and_rotates_templates():
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

    title = render_title(signals)

    assert title.startswith("Daily Retail Stock Signals - May 4, 2026:")
    assert "GME" in title
    assert "XRX" in title
    assert "Buzz" in title
    assert "Sentiment" in title

    varied = {
        render_title(
            select_daily_signals(
                date_label=date_label,
                trending_today=rows,
                trending_7d=rows,
            )
        )
        for date_label in ["May 4, 2026", "May 5, 2026", "May 6, 2026"]
    }
    assert len(varied) > 1


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
    assert title.startswith("Daily Retail Stock Signals - May 7, 2026:")


def test_render_post_keeps_question_specific_and_filters_numeric_tickers():
    rows = [
        _row("7974", 90.0, 0.05, 30, 20, [95, 90]),
        _row("NVDA", 82.0, 0.04, 29, 18, [80, 82]),
        _row("TTM", 66.0, 0.22, 58, 8, [34, 66]),
        _row("BABA", 69.0, -0.05, 18, 31, [33, 69]),
        _row("NKE", 64.0, 0.0, 17, 17, [70, 64], trend="falling"),
    ]
    signals = select_daily_signals(
        date_label="May 14, 2026",
        trending_today=rows,
        trending_7d=rows,
        explanations={"BABA": "BABA is trending because a news claim should not print."},
    )

    title = render_title(signals)
    post = render_post(signals)
    combined = f"{title}\n{post}"

    assert "7974" not in combined
    assert "news claim should not print" not in combined
    assert "Which would you weigh more today" in post
    assert "TTM's cleaner sentiment" in post
    assert "BABA's larger but negative buzz spike" in post
