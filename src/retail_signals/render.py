"""Markdown rendering for Reddit daily posts."""

from __future__ import annotations

from retail_signals.deepseek import AiCopy
from retail_signals.signals import DailySignals, StockSignal


def render_title(signals: DailySignals) -> str:
    """Render the Reddit post title."""
    return (
        f"Daily Retail Stock Signals - {signals.date_label}: "
        f"{signals.top_buzz.ticker} Leads Buzz, "
        f"{signals.cleanest_breakout.ticker} Sentiment Improves, "
        f"{signals.biggest_breakout.ticker} Moves Most"
    )


def render_post(signals: DailySignals, *, ai_copy: AiCopy | None = None) -> str:
    """Render mobile-first Reddit Markdown."""
    intro = ai_copy.intro if ai_copy else _fallback_intro(signals)
    takeaway = ai_copy.takeaway if ai_copy else _fallback_takeaway(signals)
    question = ai_copy.question if ai_copy else _fallback_question(signals)

    lines = [
        f"# Daily Retail Stock Signals - {signals.date_label}",
        "",
        intro,
        "",
        "### Signal Summary",
        "",
        *_summary_block("Top Buzz", signals.top_buzz),
        "",
        *_summary_block("Cleanest Sentiment Breakout", signals.cleanest_breakout),
        "",
        *_summary_block("Biggest 7-Day Breakout", signals.biggest_breakout),
        "",
        *_summary_block("Biggest Fade", signals.biggest_fade),
        "",
        "### Top Buzz",
        "",
        *[_top_buzz_line(index, signal) for index, signal in enumerate(signals.top_buzz_list, 1)],
        "",
        "### 7-Day Movers",
        "",
        *[_mover_line(signal) for signal in signals.movers],
        "",
        "### Takeaway",
        "",
        takeaway,
        "",
        question,
        "",
        "Data: Adanos Reddit stock sentiment - https://adanos.org/reddit-stock-sentiment  ",
        "Data-driven sentiment signal, not financial advice.",
        "",
    ]
    return "\n".join(lines)


def _summary_block(label: str, signal: StockSignal) -> list[str]:
    metric_sentence = _summary_metric_sentence(label, signal)
    metric_sentence = f"{metric_sentence} {_signal_read(label, signal)}"
    return [f"**{label}:** {signal.ticker}  ", metric_sentence]


def _summary_metric_sentence(label: str, signal: StockSignal) -> str:
    if label == "Top Buzz":
        return (
            f"Buzz **{signal.buzz_score:.1f}**, sentiment **{signal.sentiment_label}**, "
            f"bullish/bearish split **{_pct(signal.bullish_pct)} / {_pct(signal.bearish_pct)}**."
        )
    if signal.buzz_delta_7d is not None:
        direction = "moved" if signal.buzz_delta_7d >= 0 else "dropped"
        return (
            f"7-day buzz {direction} from **{signal.buzz_start_7d:.1f} to "
            f"{signal.buzz_end_7d:.1f}**. Sentiment is **{signal.sentiment_label}** "
            f"at **{_signed(signal.sentiment_score)}**, with **{_pct(signal.bullish_pct)} "
            f"bullish vs. {_pct(signal.bearish_pct)} bearish** discussion."
        )
    return f"Buzz **{signal.buzz_score:.1f}**, sentiment **{signal.sentiment_label}**."


def _signal_read(label: str, signal: StockSignal) -> str:
    """Return a data-only interpretation of the signal."""
    if label == "Top Buzz" and signal.trend == "falling":
        return (
            "This is sustained attention rather than fresh acceleration because "
            "the trend label is **falling**."
        )
    if label == "Cleanest Sentiment Breakout":
        if _has_bullish_confirmation(signal):
            return (
                "This is the cleanest sentiment breakout because buzz rose while "
                "bullish discussion stayed clearly above bearish discussion."
            )
        return "This is a buzz breakout, but sentiment confirmation is mixed."
    if label == "Biggest 7-Day Breakout":
        if signal.sentiment_score is not None and signal.sentiment_score < 0.03:
            return "The buzz move is large, but sentiment does not strongly confirm it."
        return "This is the largest 7-day buzz increase in today's top set."
    if label == "Biggest Fade":
        if signal.sentiment_score is not None and signal.sentiment_score < -0.03:
            return (
                "This is the clearest caution signal because buzz moved lower "
                "while sentiment is negative."
            )
        return (
            "This is a fade in 7-day buzz, even though absolute attention may still be elevated."
        )
    return ""


def _has_bullish_confirmation(signal: StockSignal) -> bool:
    if signal.buzz_delta_7d is None or signal.buzz_delta_7d <= 0:
        return False
    if signal.sentiment_score is None or signal.sentiment_score < 0.05:
        return False
    return (signal.bullish_pct or 0) > (signal.bearish_pct or 0)


def _top_buzz_line(index: int, signal: StockSignal) -> str:
    return (
        f"**{index}. {signal.ticker}** - Buzz **{signal.buzz_score:.1f}**, "
        f"sentiment **{signal.sentiment_label}**, {signal.trend}  "
    )


def _mover_line(signal: StockSignal) -> str:
    if signal.buzz_delta_7d is None:
        return f"**{signal.ticker}** - Buzz **{signal.buzz_score:.1f}**, {signal.sentiment_label}  "
    move = _signed(signal.buzz_delta_7d, decimals=1)
    descriptor = _mover_descriptor(signal)
    return f"**{signal.ticker}** - **{move}** buzz, {descriptor}  "


def _mover_descriptor(signal: StockSignal) -> str:
    if (signal.buzz_delta_7d or 0) < 0:
        if signal.sentiment_score is not None and signal.sentiment_score < -0.03:
            return "fading with negative sentiment"
        return "buzz fading"
    if signal.sentiment_score is not None and signal.sentiment_score >= 0.10:
        return "strong positive sentiment"
    if signal.sentiment_score is not None and signal.sentiment_score >= 0.03:
        return "positive momentum"
    if signal.sentiment_score is not None and signal.sentiment_score < -0.03:
        return "buzz up, sentiment negative"
    return "buzz up, sentiment neutral"


def _fallback_intro(signals: DailySignals) -> str:
    return (
        f"Today's signal: **{signals.top_buzz.ticker}** has the strongest Reddit buzz, "
        f"**{signals.cleanest_breakout.ticker}** is the cleanest sentiment breakout, "
        f"and **{signals.biggest_fade.ticker}** is the clearest 7-day fade."
    )


def _fallback_takeaway(signals: DailySignals) -> str:
    return (
        f"**{signals.top_buzz.ticker}** is today's attention leader, but the cleaner "
        f"sentiment signal is **{signals.cleanest_breakout.ticker}**. "
        f"**{signals.biggest_breakout.ticker}** has the biggest 7-day buzz move, while "
        f"**{signals.biggest_fade.ticker}** is the main caution signal."
    )


def _fallback_question(signals: DailySignals) -> str:
    return (
        f"Which signal looks more meaningful today: **{signals.top_buzz.ticker} attention**, "
        f"**{signals.cleanest_breakout.ticker} sentiment**, or "
        f"**{signals.biggest_fade.ticker} fade**?"
    )


def _pct(value: int | None) -> str:
    return "n/a" if value is None else f"{value}%"


def _signed(value: float | None, *, decimals: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.{decimals}f}"
