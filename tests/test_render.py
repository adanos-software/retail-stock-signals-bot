from retail_signals.deepseek import AiCopy
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


def test_render_post_uses_mobile_first_sections_with_explain_context():
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
    assert "GME has the widest attention" in post
    assert "shared eBay narrative" in post
    assert "Context:" not in post
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

    assert post.splitlines()[0] == (
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
        explanations={
            "BABA": "BABA is trending because a news claim should not print."
        },
    )

    title = render_title(signals)
    post = render_post(signals)
    combined = f"{title}\n{post}"

    assert "7974" not in combined
    assert "news claim should not print" in combined
    assert "Which part matters more here" in post
    assert "TTM's sentiment quality" in post
    assert "BABA's buzz spike" in post


def test_render_post_surfaces_sanitized_explain_context_in_summary_and_takeaway():
    rows = [
        _row("NVDA", 82.6, 0.01, 26, 21, [80, 82.6]),
        _row("GRPN", 67.0, 0.148, 36, 11, [55.6, 67.0]),
        _row("SBUX", 67.0, 0.013, 23, 18, [50.7, 67.0]),
        _row("F", 66.6, 0.021, 32, 23, [75.1, 66.6], trend="falling"),
    ]
    signals = select_daily_signals(
        date_label="May 20, 2026",
        trending_today=rows,
        trending_7d=rows,
        explanations={
            "NVDA": "NVDA is trending because demand is rising around agentic AI.",
            "GRPN": "GRPN is trending because low float and major short interest are creating a sharp buying opportunity.",
            "SBUX": "SBUX is trending because major layoffs sparked concern.",
        },
    )

    post = render_post(signals)

    assert "NVDA has the widest attention" in post
    assert "short-squeeze discussion" in post
    assert "buying opportunity" not in post
    assert (
        "The board is split between raw attention, sentiment quality, and fresh acceleration."
        in post
    )


def test_render_post_uses_deepseek_signal_reads_when_available():
    rows = [
        _row("NVDA", 82.6, 0.01, 26, 21, [80, 82.6]),
        _row("GRPN", 67.0, 0.148, 36, 11, [55.6, 67.0]),
        _row("SBUX", 67.0, 0.013, 23, 18, [50.7, 67.0]),
        _row("F", 66.6, 0.021, 32, 23, [75.1, 66.6], trend="falling"),
    ]
    signals = select_daily_signals(
        date_label="May 20, 2026",
        trending_today=rows,
        trending_7d=rows,
    )
    ai_copy = AiCopy(
        takeaway="AI takeaway.",
        signal_reads={
            "top_buzz": "NVDA analysis from DeepSeek.",
            "cleanest_breakout": "GRPN analysis from DeepSeek.",
            "biggest_breakout": "SBUX analysis from DeepSeek.",
            "biggest_fade": "F analysis from DeepSeek.",
        },
    )

    post = render_post(signals, ai_copy=ai_copy)

    assert "NVDA analysis from DeepSeek." in post
    assert "GRPN analysis from DeepSeek." in post
    assert "SBUX analysis from DeepSeek." in post
    assert "F analysis from DeepSeek." in post
    assert "AI takeaway." in post


def test_render_post_falls_back_when_deepseek_takeaway_is_empty():
    rows = [
        _row("NVDA", 82.6, 0.01, 26, 21, [80, 82.6]),
        _row("GRPN", 67.0, 0.148, 36, 11, [55.6, 67.0]),
        _row("SBUX", 67.0, 0.013, 23, 18, [50.7, 67.0]),
        _row("F", 66.6, 0.021, 32, 23, [75.1, 66.6], trend="falling"),
    ]
    signals = select_daily_signals(
        date_label="May 20, 2026",
        trending_today=rows,
        trending_7d=rows,
    )
    ai_copy = AiCopy(
        takeaway="", signal_reads={"top_buzz": "NVDA analysis from DeepSeek."}
    )

    post = render_post(signals, ai_copy=ai_copy)

    assert "NVDA analysis from DeepSeek." in post
    assert "**NVDA** owns the buzz lead" in post


def test_select_and_render_all_down_market_without_false_breakout():
    rows = [
        _row("TOP", 82.0, 0.08, 40, 20, [90.0, 82.0], trend="falling"),
        _row("LESS", 70.0, 0.12, 45, 15, [73.0, 70.0], trend="falling"),
        _row("MOST", 61.0, -0.08, 18, 38, [75.0, 61.0], trend="falling"),
    ]

    signals = select_daily_signals(
        date_label="August 9, 2026",
        trending_today=rows,
        trending_7d=rows,
    )
    rendered = f"{render_title(signals)}\n{render_post(signals)}"

    assert signals.biggest_breakout is None
    assert signals.cleanest_breakout is None
    assert "Largest 7-Day Buzz Move" not in rendered
    assert "Best Sentiment Read" not in rendered
    assert "LESS Moves Most" not in rendered
    assert "LESS Has Stronger Sentiment" not in rendered
    assert "MOST" in rendered
    assert "7-Day Buzz Fade" in rendered


def test_select_and_render_all_up_market_without_false_fade():
    rows = [
        _row("TOP", 82.0, 0.08, 40, 20, [70.0, 82.0]),
        _row("MOST", 74.0, 0.12, 45, 15, [30.0, 74.0]),
        _row("LESS", 61.0, -0.02, 22, 25, [58.0, 61.0]),
    ]

    signals = select_daily_signals(
        date_label="August 9, 2026",
        trending_today=rows,
        trending_7d=rows,
    )
    rendered = f"{render_title(signals)}\n{render_post(signals)}"

    assert signals.biggest_fade is None
    assert signals.biggest_breakout is not None
    assert signals.biggest_breakout.buzz_delta_7d > 0
    assert "7-Day Buzz Fade" not in rendered
    assert "showing where attention cooled" not in rendered


def test_select_and_render_attention_jump_without_false_sentiment_role():
    rows = [
        _row("TOP", 82.0, -0.08, 18, 38, [70.0, 82.0]),
        _row("MOST", 74.0, -0.12, 15, 45, [30.0, 74.0]),
    ]

    signals = select_daily_signals(
        date_label="August 9, 2026",
        trending_today=rows,
        trending_7d=rows,
    )
    rendered = f"{render_title(signals)}\n{render_post(signals)}"

    assert signals.biggest_breakout is not None
    assert signals.cleanest_breakout is None
    assert "Best Sentiment Read" not in rendered
    assert "Has Stronger Sentiment" not in rendered
    assert "Sentiment Improves" not in rendered
    assert "Attention Jumps" in rendered


def test_select_and_render_flat_market_without_directional_labels():
    rows = [
        _row("TOP", 82.0, 0.08, 40, 20, [82.0, 82.0]),
        _row("FLAT", 70.0, -0.02, 22, 25, [70.0, 70.0]),
    ]

    signals = select_daily_signals(
        date_label="August 9, 2026",
        trending_today=rows,
        trending_7d=rows,
    )
    rendered = f"{render_title(signals)}\n{render_post(signals)}"

    assert signals.biggest_breakout is None
    assert signals.cleanest_breakout is None
    assert signals.biggest_fade is None
    assert "Largest 7-Day Buzz Move" not in rendered
    assert "7-Day Buzz Fade" not in rendered
    assert "7-Day Attention Is Flat" in rendered
