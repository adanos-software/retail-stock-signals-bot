"""Markdown rendering for Reddit daily posts."""

from __future__ import annotations

from retail_signals.deepseek import AiCopy
from retail_signals.signals import DailySignals, StockSignal


def render_title(signals: DailySignals) -> str:
    """Render the Reddit post title."""
    templates = [
        "{top} Leads Buzz, {clean} Has Stronger Sentiment",
        "{top} Buzz Leads, {clean} Sentiment Improves",
        "{top} Leads Buzz, {big} Moves Most",
    ]
    template = templates[_rotation_index(signals.date_label, len(templates))]
    suffix = template.format(
        top=signals.top_buzz.ticker,
        clean=signals.cleanest_breakout.ticker,
        big=signals.biggest_breakout.ticker,
    )
    return f"Daily Retail Stock Signals - {signals.date_label}: {suffix}"


def render_post(signals: DailySignals, *, ai_copy: AiCopy | None = None) -> str:
    """Render mobile-first Reddit Markdown."""
    intro = _contrast_intro(signals)
    takeaway = ai_copy.takeaway if ai_copy and ai_copy.takeaway else _fallback_takeaway(signals)
    signal_reads = ai_copy.signal_reads if ai_copy else {}
    question = _engagement_question(signals)

    lines = [
        intro,
        "",
        "### Signal Summary",
        "",
        *_summary_block("Top Buzz", signals.top_buzz, signal_reads.get("top_buzz")),
        "",
        *_summary_block(
            "Best Sentiment Read",
            signals.cleanest_breakout,
            signal_reads.get("cleanest_breakout"),
        ),
        "",
        *_summary_block(
            "Largest 7-Day Buzz Move",
            signals.biggest_breakout,
            signal_reads.get("biggest_breakout"),
        ),
        "",
        *_summary_block("7-Day Buzz Fade", signals.biggest_fade, signal_reads.get("biggest_fade")),
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


def _summary_block(label: str, signal: StockSignal, analysis: str | None = None) -> list[str]:
    return [
        f"**{label}: {signal.ticker}**  ",
        _summary_metric_line(label, signal),
        analysis or _signal_read(label, signal),
    ]


def _summary_metric_line(label: str, signal: StockSignal) -> str:
    if label == "Top Buzz":
        return (
            f"Buzz **{signal.buzz_score:.1f}** | Sentiment **{signal.sentiment_label}** | "
            f"Bull/Bear **{_pct(signal.bullish_pct)} / {_pct(signal.bearish_pct)}**  "
        )
    if signal.buzz_delta_7d is not None:
        return (
            f"7D Buzz **{_signed(signal.buzz_delta_7d, decimals=1)}** "
            f"({_fmt(signal.buzz_start_7d)} -> {_fmt(signal.buzz_end_7d)}) | "
            f"Sentiment **{signal.sentiment_label}** ({_signed(signal.sentiment_score)}) | "
            f"Bull/Bear **{_pct(signal.bullish_pct)} / {_pct(signal.bearish_pct)}**  "
        )
    return f"Buzz **{signal.buzz_score:.1f}** | Sentiment **{signal.sentiment_label}**  "


def _signal_read(label: str, signal: StockSignal) -> str:
    """Return a data-only interpretation of the signal."""
    context = _context_clause(signal) if signal.explanation else ""
    if label == "Top Buzz" and signal.trend == "falling":
        if context:
            return (
                f"Reddit discussion points to {context}, but the falling trend label makes this look "
                "more like sustained attention than fresh acceleration."
            )
        return "High absolute attention, but the falling trend label makes it look more like sustained buzz than fresh acceleration."
    if label == "Top Buzz":
        if context:
            return (
                f"{signal.ticker} has the widest attention, while Reddit discussion points to "
                f"{context}; neutral sentiment keeps it from reading like broad bullish confirmation."
            )
        return "The broadest attention signal in today's Reddit data."
    if label == "Best Sentiment Read":
        if _has_bullish_confirmation(signal):
            if context:
                return (
                    f"{signal.ticker} is the cleaner sentiment read: buzz rose, bulls led bears, "
                    f"and Reddit discussion points to {context}."
                )
            return "The best-confirmed sentiment read: buzz rose and bullish discussion stayed clearly ahead of bearish discussion."
        if context:
            return (
                f"{signal.ticker} has the better sentiment profile, but Reddit discussion points to "
                f"{context}, so the read is not purely metric-driven."
            )
        return "A buzz mover with mixed sentiment confirmation."
    if label == "Largest 7-Day Buzz Move":
        if signal.sentiment_score is not None and signal.sentiment_score < 0.03:
            if context:
                return (
                    f"{signal.ticker} had the biggest attention jump, but sentiment stayed muted; "
                    f"Reddit discussion points to {context}."
                )
            return "The largest attention jump, but sentiment does not strongly confirm it."
        if context:
            return (
                f"{signal.ticker} had the fastest 7-day attention expansion, with Reddit discussion "
                f"pointing to {context}."
            )
        return "The fastest 7-day attention expansion in today's top set."
    if label == "7-Day Buzz Fade":
        if signal.sentiment_score is not None and signal.sentiment_score < -0.03:
            if context:
                return (
                    f"{signal.ticker} cooled while sentiment was negative, and Reddit discussion "
                    f"points to {context}."
                )
            return "Attention cooled while sentiment was negative, making it the clearest caution read."
        if context:
            return (
                f"{signal.ticker} lost attention over 7 days, but Reddit discussion points to "
                f"{context}, so the fade is not a clean negative sentiment read."
            )
        return "Attention cooled over 7 days, but the sentiment read is not strongly negative."
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


def _contrast_intro(signals: DailySignals) -> str:
    if signals.biggest_breakout.sentiment_score is not None and signals.biggest_breakout.sentiment_score < -0.03:
        return (
            f"Today's split: **{signals.top_buzz.ticker}** had the attention, "
            f"**{signals.cleanest_breakout.ticker}** had the cleaner sentiment read, "
            f"and **{signals.biggest_breakout.ticker}** drew the largest 7-day buzz jump with negative sentiment."
        )
    if signals.top_buzz.ticker != signals.cleanest_breakout.ticker:
        return (
            f"Today's split: **{signals.top_buzz.ticker}** led raw buzz, but "
            f"**{signals.cleanest_breakout.ticker}** had the cleaner sentiment profile."
        )
    return (
        f"Today's signal is more aligned: **{signals.top_buzz.ticker}** led buzz and also carried "
        f"the strongest sentiment profile in today's top set."
    )


def _fallback_takeaway(signals: DailySignals) -> str:
    top_context = _context_clause(signals.top_buzz) if signals.top_buzz.explanation else ""
    clean_context = _context_clause(signals.cleanest_breakout) if signals.cleanest_breakout.explanation else ""
    breakout_context = _context_clause(signals.biggest_breakout) if signals.biggest_breakout.explanation else ""

    if signals.biggest_breakout.sentiment_score is not None and signals.biggest_breakout.sentiment_score < -0.03:
        return (
            f"The board is split between attention, sentiment quality, and risk. "
            f"**{signals.top_buzz.ticker}** owns raw buzz"
            f"{_context_fragment(top_context)}, while **{signals.cleanest_breakout.ticker}** has the cleaner "
            f"sentiment profile{_context_fragment(clean_context)}. **{signals.biggest_breakout.ticker}** had "
            f"the biggest 7-day buzz jump, but its negative sentiment makes the move look contested"
            f"{_context_fragment(breakout_context)}."
        )
    return (
        f"The board is split between raw attention, sentiment quality, and fresh acceleration. "
        f"**{signals.top_buzz.ticker}** owns the buzz lead{_context_fragment(top_context)}, while "
        f"**{signals.cleanest_breakout.ticker}** has the cleaner sentiment read"
        f"{_context_fragment(clean_context)}. **{signals.biggest_breakout.ticker}** is the real 7-day "
        f"acceleration signal{_context_fragment(breakout_context)}, with **{signals.biggest_fade.ticker}** "
        "showing where attention cooled."
    )


def _engagement_question(signals: DailySignals) -> str:
    if signals.biggest_breakout.explanation and signals.biggest_breakout.ticker != signals.cleanest_breakout.ticker:
        return (
            f"Which part matters more here: **{signals.cleanest_breakout.ticker}'s sentiment quality** "
            f"or the context behind **{signals.biggest_breakout.ticker}'s buzz spike**?"
        )
    if signals.biggest_breakout.sentiment_score is not None and signals.biggest_breakout.sentiment_score < -0.03:
        return (
            f"Which would you weigh more today: **{signals.cleanest_breakout.ticker}'s cleaner sentiment** "
            f"or **{signals.biggest_breakout.ticker}'s larger but negative buzz spike**?"
        )
    if signals.top_buzz.ticker != signals.cleanest_breakout.ticker:
        return (
            f"Would you trust **{signals.top_buzz.ticker}'s broad attention** or "
            f"**{signals.cleanest_breakout.ticker}'s cleaner sentiment read** more here?"
        )
    return (
        f"Is **{signals.top_buzz.ticker}** more interesting here as a buzz leader, "
        f"a sentiment signal, or both?"
    )


def _pct(value: int | None) -> str:
    return "n/a" if value is None else f"{value}%"


def _signed(value: float | None, *, decimals: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.{decimals}f}"


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def _context_clause(signal: StockSignal) -> str:
    prefix = "Reddit discussion points to "
    explanation = signal.explanation
    if explanation.startswith(prefix):
        explanation = explanation[len(prefix) :]
    explanation = explanation.rstrip(".")
    return explanation[:1].lower() + explanation[1:]


def _context_fragment(context: str) -> str:
    if not context:
        return ""
    return f", with Reddit context around {context}"


def _rotation_index(seed: str, count: int) -> int:
    return sum(seed.encode("utf-8")) % count
