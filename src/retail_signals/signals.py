"""Signal selection for daily Reddit stock posts."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

_TICKER_RE = re.compile(r"^(?=.{1,15}$)[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)*$")


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
    cleanest_breakout: StockSignal | None
    biggest_breakout: StockSignal | None
    biggest_fade: StockSignal | None
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
    today_signals = _unique_signals(
        [
            signal
            for row in trending_today
            if (signal := _from_row(row, explanations=explanations)) is not None
        ]
    )
    seven_day_signals = _unique_signals(
        [
            signal
            for row in trending_7d
            if (
                signal := _from_row(
                    row,
                    explanations=explanations,
                    include_delta=True,
                )
            )
            is not None
        ]
    )
    seven_day_signals = [
        signal for signal in seven_day_signals if signal.buzz_delta_7d is not None
    ]
    if not today_signals:
        raise ValueError("trending_today must include at least one valid ticker")
    if not seven_day_signals:
        raise ValueError("trending_7d rows must include trend_history")

    top_buzz = max(today_signals, key=lambda signal: signal.buzz_score)
    gainers = sorted(
        (signal for signal in seven_day_signals if (signal.buzz_delta_7d or 0) > 0),
        key=lambda signal: signal.buzz_delta_7d or 0,
        reverse=True,
    )
    faders = sorted(
        (signal for signal in seven_day_signals if (signal.buzz_delta_7d or 0) < 0),
        key=lambda signal: signal.buzz_delta_7d or 0,
    )

    quality_candidates = [
        signal
        for signal in gainers
        if (signal.buzz_delta_7d or 0) > 0
        and (signal.sentiment_score or 0) >= 0.05
        and (signal.bullish_pct or 0) > (signal.bearish_pct or 0)
        and signal.buzz_score >= 60
    ]
    cleanest_breakout = (
        max(
            quality_candidates,
            key=lambda signal: (
                signal.sentiment_score or 0,
                signal.buzz_delta_7d or 0,
                signal.buzz_score,
            ),
        )
        if quality_candidates
        else None
    )

    return DailySignals(
        date_label=date_label,
        top_buzz=top_buzz,
        cleanest_breakout=cleanest_breakout,
        biggest_breakout=gainers[0] if gainers else None,
        biggest_fade=faders[0] if faders else None,
        top_buzz_list=sorted(
            today_signals, key=lambda signal: signal.buzz_score, reverse=True
        )[:5],
        movers=_unique_signals([*gainers[:5], *faders[:3]]),
    )


def tickers_requiring_explanations(signals: DailySignals) -> list[str]:
    """Return the unique tickers that should get context from the explain endpoint."""
    return [signal.ticker for signal in _selected_context_signals(signals)]


def resolve_shared_narrative_explanations(
    signals: DailySignals,
    explanations: dict[str, str],
) -> dict[str, str]:
    """Replace generic explanations when another selected ticker explains the shared narrative."""
    resolved = dict(explanations)
    selected = _selected_context_signals(signals)

    for target in selected:
        target_explanation = resolved.get(target.ticker, "")
        if (
            target_explanation
            and "without a clear catalyst" not in target_explanation.lower()
        ):
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


def sanitize_explanation(ticker: str, explanation: str) -> str:
    """Return a conservative Reddit-context sentence or empty string."""
    cleaned = " ".join(explanation.strip().split())
    if not cleaned or _is_unsafe_explanation(cleaned):
        return ""

    prefix = f"{ticker.upper()} is trending because "
    if cleaned.lower().startswith(prefix.lower()):
        cleaned = cleaned[len(prefix) :]
    elif cleaned.lower().startswith("is trending because "):
        cleaned = cleaned[len("is trending because ") :]
    if cleaned.lower().startswith("of "):
        cleaned = cleaned[3:]

    cleaned = _soften_explanation_claims(cleaned)
    if not cleaned:
        return ""
    cleaned = f"Reddit discussion points to {cleaned}"

    return cleaned[:260].rstrip()


def _from_row(
    row: dict[str, Any],
    *,
    explanations: dict[str, str],
    include_delta: bool = False,
) -> StockSignal | None:
    if not isinstance(row, dict):
        return None
    ticker = str(row.get("ticker") or "").strip().upper()
    if not _is_public_stock_ticker(ticker):
        return None

    try:
        buzz_score = _required_number(row.get("buzz_score"))
        sentiment_score = _optional_number(row.get("sentiment_score"))
        bullish_pct = _optional_integer(row.get("bullish_pct"))
        bearish_pct = _optional_integer(row.get("bearish_pct"))
        subreddit_count = _optional_integer(row.get("subreddit_count"))
    except (TypeError, ValueError):
        return None
    if not 0 <= buzz_score <= 100:
        return None
    if sentiment_score is not None and not -1 <= sentiment_score <= 1:
        return None
    if bullish_pct is not None and not 0 <= bullish_pct <= 100:
        return None
    if bearish_pct is not None and not 0 <= bearish_pct <= 100:
        return None
    if (
        bullish_pct is not None
        and bearish_pct is not None
        and bullish_pct + bearish_pct > 100
    ):
        return None
    if subreddit_count is not None and subreddit_count < 0:
        return None

    buzz_delta = None
    buzz_start = None
    buzz_end = None
    if include_delta:
        history = row.get("trend_history")
        if isinstance(history, list) and len(history) >= 2:
            try:
                buzz_start = _required_number(history[0])
                buzz_end = _required_number(history[-1])
            except (TypeError, ValueError):
                buzz_start = None
                buzz_end = None
            else:
                if 0 <= buzz_start <= 100 and 0 <= buzz_end <= 100:
                    buzz_delta = round(buzz_end - buzz_start, 1)
                else:
                    buzz_start = None
                    buzz_end = None

    return StockSignal(
        ticker=ticker,
        company_name=str(row.get("company_name") or ticker),
        buzz_score=buzz_score,
        sentiment_score=sentiment_score,
        bullish_pct=bullish_pct,
        bearish_pct=bearish_pct,
        trend=str(row.get("trend") or "stable").lower(),
        subreddit_count=subreddit_count,
        buzz_delta_7d=buzz_delta,
        buzz_start_7d=buzz_start,
        buzz_end_7d=buzz_end,
        explanation=sanitize_explanation(ticker, explanations.get(ticker, "")),
    )


def _required_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("value must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("value must be finite")
    return parsed


def _optional_number(value: Any) -> float | None:
    if value is None:
        return None
    return _required_number(value)


def _optional_integer(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("value must be an integer")
    return value


def _is_public_stock_ticker(ticker: str) -> bool:
    return _TICKER_RE.fullmatch(ticker) is not None


def _unique_signals(signals: list[StockSignal]) -> list[StockSignal]:
    seen: set[str] = set()
    result: list[StockSignal] = []
    for signal in signals:
        if signal.ticker not in seen:
            result.append(signal)
            seen.add(signal.ticker)
    return result


def _selected_context_signals(signals: DailySignals) -> list[StockSignal]:
    ordered: list[StockSignal | None] = [
        signals.top_buzz,
        signals.cleanest_breakout,
        signals.biggest_breakout,
        signals.biggest_fade,
        *signals.top_buzz_list[:3],
    ]
    seen: set[str] = set()
    result: list[StockSignal] = []
    for signal in ordered:
        if signal is None:
            continue
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


def _is_unsafe_explanation(explanation: str) -> bool:
    lowered = explanation.lower()
    if "without a clear catalyst" in lowered:
        return True
    unsafe_fragments = ['"that stupid"', "passed nvidia", "price target"]
    return any(fragment in lowered for fragment in unsafe_fragments)


def _soften_explanation_claims(explanation: str) -> str:
    """Keep useful explain context while removing trading-call phrasing."""
    replacements = {
        "demand going parabolic": "surging demand",
        "major demand driven by": "major demand tied to",
        "driven by": "tied to",
        "low float and major short interest are creating a sharp buying opportunity": (
            "low float, major short interest, and short-squeeze discussion"
        ),
        "low float and major short interest are creating short-squeeze interest": (
            "low float, major short interest, and short-squeeze discussion"
        ),
        "concern about the potential for a short squeeze": "concern about volatility",
        "potential for a short squeeze": "short-squeeze potential",
        "major short interest being cited as a potential trigger for a sharp short squeeze": (
            "major short interest and short-interest speculation"
        ),
        "concern about a potential sharp decline": "downside concern",
        "sharp short squeeze": "short-interest move",
        "short squeeze": "short-interest narrative",
        "potential sharp decline": "downside concern",
        "sharp decline": "downside concern",
        "sparking optimism": "adding optimism",
        "sparked optimism": "added optimism",
        "a sharp buying opportunity": "short-squeeze interest",
        "buying opportunity": "retail interest",
        "potential for higher capital gains": "upside speculation",
        "long positions": "long-side interest",
        "loading up on the stock": "adding exposure",
        "china agreed": "China agreed",
    }
    cleaned = explanation
    for source, target in replacements.items():
        cleaned = cleaned.replace(source, target)
    return cleaned.strip()
