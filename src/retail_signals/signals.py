"""Signal selection for daily Reddit stock posts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StockSignal:
    """Normalized stock signal used by the renderer and AI prompt."""

    ticker: str
    company_name: str
    buzz_score: float
    sentiment_score: float | None
    bullish_pct: int | None
    bearish_pct: int | None
    trend: str
    subreddit_count: int | None
    buzz_delta_7d: float | None = None
    buzz_start_7d: float | None = None
    buzz_end_7d: float | None = None
    explanation: str = ""

    @property
    def sentiment_label(self) -> str:
        """Return a compact Reddit-friendly sentiment label."""
        if self.sentiment_score is None:
            return "neutral"
        if self.sentiment_score >= 0.10:
            return "strong positive"
        if self.sentiment_score >= 0.03:
            return "positive"
        if self.sentiment_score <= -0.10:
            return "strong negative"
        if self.sentiment_score <= -0.03:
            return "negative"
        return "neutral"


@dataclass(frozen=True)
class DailySignals:
    """Selected data for one daily post."""

    date_label: str
    top_buzz: StockSignal
    cleanest_breakout: StockSignal
    biggest_breakout: StockSignal
    biggest_fade: StockSignal
    top_buzz_list: list[StockSignal]
    movers: list[StockSignal]


def select_daily_signals(
    *,
    date_label: str,
    trending_today: list[dict[str, Any]],
    trending_7d: list[dict[str, Any]],
    explanations: dict[str, str] | None = None,
) -> DailySignals:
    """Select top buzz, 7-day movers, and high-quality sentiment breakout."""
    if not trending_today:
        raise ValueError("trending_today must not be empty")
    if not trending_7d:
        raise ValueError("trending_7d must not be empty")

    explanations = explanations or {}
    today_signals = [_from_row(row, explanations=explanations) for row in trending_today]
    seven_day_signals = [
        _from_row(row, explanations=explanations, include_delta=True)
        for row in trending_7d
    ]
    seven_day_signals = [signal for signal in seven_day_signals if signal.buzz_delta_7d is not None]
    if not seven_day_signals:
        raise ValueError("trending_7d rows must include trend_history")

    top_buzz = max(today_signals, key=lambda signal: signal.buzz_score)
    gainers = sorted(seven_day_signals, key=lambda signal: signal.buzz_delta_7d or 0, reverse=True)
    faders = sorted(seven_day_signals, key=lambda signal: signal.buzz_delta_7d or 0)

    quality_candidates = [
        signal
        for signal in gainers
        if (signal.buzz_delta_7d or 0) > 0
        and (signal.sentiment_score or 0) >= 0.05
        and (signal.bullish_pct or 0) > (signal.bearish_pct or 0)
        and signal.buzz_score >= 60
    ]
    cleanest_breakout = max(
        quality_candidates or gainers[:1],
        key=lambda signal: (
            signal.sentiment_score or 0,
            signal.buzz_delta_7d or 0,
            signal.buzz_score,
        ),
    )

    return DailySignals(
        date_label=date_label,
        top_buzz=top_buzz,
        cleanest_breakout=cleanest_breakout,
        biggest_breakout=gainers[0],
        biggest_fade=faders[0],
        top_buzz_list=sorted(today_signals, key=lambda signal: signal.buzz_score, reverse=True)[:5],
        movers=[*gainers[:5], *faders[:3]],
    )


def tickers_requiring_explanations(signals: DailySignals) -> list[str]:
    """Return the unique tickers that should get context from the explain endpoint."""
    ordered = [
        signals.top_buzz.ticker,
        signals.cleanest_breakout.ticker,
        signals.biggest_breakout.ticker,
        signals.biggest_fade.ticker,
        *[signal.ticker for signal in signals.top_buzz_list[:3]],
    ]
    seen: set[str] = set()
    result: list[str] = []
    for ticker in ordered:
        if ticker not in seen:
            result.append(ticker)
            seen.add(ticker)
    return result


def resolve_shared_narrative_explanations(
    signals: DailySignals,
    explanations: dict[str, str],
) -> dict[str, str]:
    """Replace generic explanations when another selected ticker explains the shared narrative."""
    resolved = dict(explanations)
    selected = _selected_context_signals(signals)

    for target in selected:
        target_explanation = resolved.get(target.ticker, "")
        if target_explanation and "without a clear catalyst" not in target_explanation.lower():
            continue

        target_aliases = _explanation_aliases(target)
        for source in selected:
            if source.ticker == target.ticker:
                continue
            source_explanation = resolved.get(source.ticker, "")
            if not source_explanation:
                continue
            source_lower = source_explanation.lower()
            if any(alias in source_lower for alias in target_aliases):
                resolved[target.ticker] = (
                    f"{target.ticker} appears tied to the same {source.ticker}/{target.ticker} "
                    f"narrative: {source_explanation}"
                )
                break

    return resolved


def _from_row(
    row: dict[str, Any],
    *,
    explanations: dict[str, str],
    include_delta: bool = False,
) -> StockSignal:
    ticker = str(row.get("ticker") or "").strip().upper()
    if not ticker:
        raise ValueError("row missing ticker")

    buzz_delta = None
    buzz_start = None
    buzz_end = None
    if include_delta:
        history = row.get("trend_history") or []
        if len(history) >= 2 and history[0] is not None and history[-1] is not None:
            buzz_start = float(history[0])
            buzz_end = float(history[-1])
            buzz_delta = round(buzz_end - buzz_start, 1)

    return StockSignal(
        ticker=ticker,
        company_name=str(row.get("company_name") or ticker),
        buzz_score=float(row.get("buzz_score") or 0.0),
        sentiment_score=_optional_float(row.get("sentiment_score")),
        bullish_pct=_optional_int(row.get("bullish_pct")),
        bearish_pct=_optional_int(row.get("bearish_pct")),
        trend=str(row.get("trend") or "stable").lower(),
        subreddit_count=_optional_int(row.get("subreddit_count")),
        buzz_delta_7d=buzz_delta,
        buzz_start_7d=buzz_start,
        buzz_end_7d=buzz_end,
        explanation=explanations.get(ticker, ""),
    )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _selected_context_signals(signals: DailySignals) -> list[StockSignal]:
    ordered = [
        signals.top_buzz,
        signals.cleanest_breakout,
        signals.biggest_breakout,
        signals.biggest_fade,
        *signals.top_buzz_list[:3],
    ]
    seen: set[str] = set()
    result: list[StockSignal] = []
    for signal in ordered:
        if signal.ticker not in seen:
            result.append(signal)
            seen.add(signal.ticker)
    return result


def _explanation_aliases(signal: StockSignal) -> list[str]:
    aliases = {signal.ticker.lower()}
    cleaned_name = (
        signal.company_name.lower()
        .replace(" corporation", "")
        .replace(" corp", "")
        .replace(" company", "")
        .replace(" inc", "")
        .replace(" class a", "")
        .replace(".", "")
    )
    first_token = cleaned_name.split()[0] if cleaned_name.split() else ""
    if len(first_token) >= 3:
        aliases.add(first_token)
    return sorted(aliases)
