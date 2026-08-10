"""Point-in-time Adanos snapshots and a falsifiable research signal.

This module deliberately produces research candidates, not orders.  Narrative
explanations and LLM output never enter the numeric signal path.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from retail_signals.adanos import AdanosClient, validate_base_url

SNAPSHOT_SCHEMA = "adanos.reddit-stocks.research-snapshot.v1"
FINALIZATION_TIME_UTC = time(6, 0)
_TICKER_RE = re.compile(r"^(?=.{1,15}$)[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)*$")


@dataclass(frozen=True)
class ResearchConfig:
    """Pre-registered screening defaults; they are hypotheses, not fitted alpha."""

    min_sentiment: float = 0.05
    min_bull_bear_spread: int = 10
    min_mentions: int = 20
    min_unique_posts: int = 5
    min_subreddits: int = 3
    max_crowding_buzz: float = 85.0
    max_candidates: int = 5

    def __post_init__(self) -> None:
        if not 0 < self.min_sentiment <= 1:
            raise ValueError("min_sentiment must be in (0, 1]")
        if not 0 < self.min_bull_bear_spread <= 100:
            raise ValueError("min_bull_bear_spread must be in (0, 100]")
        if min(self.min_mentions, self.min_unique_posts, self.min_subreddits) < 0:
            raise ValueError("minimum activity fields must not be negative")
        if not 0 < self.max_crowding_buzz <= 100:
            raise ValueError("max_crowding_buzz must be in (0, 100]")
        if self.max_candidates < 1:
            raise ValueError("max_candidates must be positive")


@dataclass(frozen=True)
class ResearchCandidate:
    """A long-only research candidate selected from one closed-day snapshot."""

    ticker: str
    score: float
    sentiment_score: float
    bull_bear_spread: int
    mentions: int
    unique_posts: int
    subreddit_count: int
    buzz_score: float


@dataclass(frozen=True)
class ResearchSnapshot:
    """Immutable, closed-window feature snapshot used by the backtester."""

    observed_at_utc: datetime
    window_start: date
    window_end: date
    rows: tuple[dict[str, Any], ...]
    content_sha256: str
    request: dict[str, Any]
    universe: str = "adanos-reddit-trending-top-100"
    schema: str = SNAPSHOT_SCHEMA

    def __post_init__(self) -> None:
        if self.observed_at_utc.tzinfo is None:
            raise ValueError("observed_at_utc must be timezone-aware")
        if self.observed_at_utc.utcoffset() != UTC.utcoffset(self.observed_at_utc):
            raise ValueError("observed_at_utc must use UTC")
        if self.window_start > self.window_end:
            raise ValueError("window_start must be on or before window_end")
        if self.window_start != self.window_end:
            raise ValueError("v1 research snapshots must contain exactly one UTC day")
        if self.window_end >= self.observed_at_utc.date():
            raise ValueError("research snapshots must contain only completed UTC days")
        if (
            self.window_end == self.observed_at_utc.date() - timedelta(days=1)
            and self.observed_at_utc.time() < FINALIZATION_TIME_UTC
        ):
            raise ValueError(
                "previous-day snapshots require the 06:00 UTC finalization cutoff"
            )
        if self.schema != SNAPSHOT_SCHEMA:
            raise ValueError(f"unsupported snapshot schema: {self.schema}")
        if self.content_sha256 != _snapshot_sha256(
            schema=self.schema,
            observed_at_utc=self.observed_at_utc,
            window_start=self.window_start,
            window_end=self.window_end,
            universe=self.universe,
            request_metadata=self.request,
            rows=self.rows,
        ):
            raise ValueError("snapshot content_sha256 does not match its manifest")
        request_limit = _validate_request(
            self.request, self.window_start, self.window_end
        )
        if self.universe != f"adanos-reddit-trending-top-{request_limit}":
            raise ValueError("snapshot universe does not match its request limit")
        _validate_snapshot_rows(self.rows, request_limit)

    def to_dict(self) -> dict[str, Any]:
        """Return a deterministic JSON-serializable representation."""
        if self.content_sha256 != _snapshot_sha256(
            schema=self.schema,
            observed_at_utc=self.observed_at_utc,
            window_start=self.window_start,
            window_end=self.window_end,
            universe=self.universe,
            request_metadata=self.request,
            rows=self.rows,
        ):
            raise ValueError("snapshot content changed after validation")
        request_limit = _validate_request(
            self.request, self.window_start, self.window_end
        )
        if self.universe != f"adanos-reddit-trending-top-{request_limit}":
            raise ValueError("snapshot universe changed after validation")
        _validate_snapshot_rows(self.rows, request_limit)
        return {
            "schema": self.schema,
            "observed_at_utc": self.observed_at_utc.isoformat().replace("+00:00", "Z"),
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "universe": self.universe,
            "request": self.request,
            "content_sha256": self.content_sha256,
            "rows": list(self.rows),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ResearchSnapshot:
        """Validate and decode one snapshot object."""
        rows = payload.get("rows")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("snapshot rows must be a list of objects")
        return cls(
            schema=str(payload.get("schema") or ""),
            observed_at_utc=_parse_utc_datetime(payload.get("observed_at_utc")),
            window_start=date.fromisoformat(str(payload.get("window_start"))),
            window_end=date.fromisoformat(str(payload.get("window_end"))),
            universe=str(payload.get("universe") or ""),
            request=payload.get("request")
            if isinstance(payload.get("request"), dict)
            else {},
            content_sha256=str(payload.get("content_sha256") or ""),
            rows=tuple(rows),
        )


def capture_closed_snapshot(
    client: AdanosClient,
    *,
    window_end: date,
    limit: int = 100,
    _clock: Callable[[], datetime] | None = None,
) -> ResearchSnapshot:
    """Fetch a closed UTC day and attach retrieval time plus a content hash."""
    now_utc = _clock or (lambda: datetime.now(UTC))
    request_started_at = now_utc()
    if request_started_at.tzinfo is None:
        raise ValueError("observed_at_utc must be timezone-aware")
    request_started_at = request_started_at.astimezone(UTC)
    if not 1 <= limit <= 100:
        raise ValueError("limit must be in [1, 100]")
    if window_end >= request_started_at.date():
        raise ValueError("window_end must be earlier than the UTC retrieval date")
    if (
        window_end == request_started_at.date() - timedelta(days=1)
        and request_started_at.time() < FINALIZATION_TIME_UTC
    ):
        raise ValueError("wait until 06:00 UTC for previous-day finalization")

    rows = client.get_trending_window(
        window_start=window_end,
        window_end=window_end,
        limit=limit,
    )
    normalized_rows = tuple(_canonicalize_row(row) for row in rows)
    _validate_snapshot_rows(normalized_rows, limit)
    request_metadata = {
        "base_url": client.base_url.rstrip("/"),
        "path": "/reddit/stocks/v1/trending",
        "params": {
            "from": window_end.isoformat(),
            "to": window_end.isoformat(),
            "limit": limit,
            "offset": 0,
            "type": "stock",
        },
    }
    observed_at = now_utc()
    if observed_at.tzinfo is None:
        raise ValueError("response completion time must be timezone-aware")
    observed_at = observed_at.astimezone(UTC)
    if observed_at < request_started_at:
        raise ValueError("response completion time precedes request start")
    universe = f"adanos-reddit-trending-top-{limit}"
    return ResearchSnapshot(
        observed_at_utc=observed_at,
        window_start=window_end,
        window_end=window_end,
        rows=normalized_rows,
        request=request_metadata,
        universe=universe,
        content_sha256=_snapshot_sha256(
            schema=SNAPSHOT_SCHEMA,
            observed_at_utc=observed_at,
            window_start=window_end,
            window_end=window_end,
            universe=universe,
            request_metadata=request_metadata,
            rows=normalized_rows,
        ),
    )


def write_snapshot(snapshot: ResearchSnapshot, output_path: Path) -> None:
    """Write one validated snapshot without mutating an existing file."""
    serialized = json.dumps(snapshot.to_dict(), indent=2, sort_keys=True) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output_path.open("x", encoding="utf-8") as handle:
            handle.write(serialized)
    except FileExistsError as exc:
        raise FileExistsError(f"refusing to overwrite snapshot: {output_path}") from exc


def load_snapshots(paths: Iterable[Path]) -> list[ResearchSnapshot]:
    """Load, validate, de-duplicate, and chronologically sort snapshot files."""
    snapshots: list[ResearchSnapshot] = []
    seen: set[tuple[datetime, str]] = set()
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"snapshot must be a JSON object: {path}")
        snapshot = ResearchSnapshot.from_dict(payload)
        key = (snapshot.observed_at_utc, snapshot.content_sha256)
        if key not in seen:
            snapshots.append(snapshot)
            seen.add(key)
    return sorted(snapshots, key=lambda item: item.observed_at_utc)


def select_research_candidates(
    snapshot: ResearchSnapshot,
    config: ResearchConfig,
) -> list[ResearchCandidate]:
    """Select direction-plus-quality candidates while treating buzz as crowding."""
    return rank_research_candidates(snapshot, config)[: config.max_candidates]


def rank_research_candidates(
    snapshot: ResearchSnapshot,
    config: ResearchConfig,
) -> list[ResearchCandidate]:
    """Return every socially eligible candidate in deterministic score order."""
    candidates, _ = screen_research_candidates(snapshot, config)
    return candidates


def screen_research_candidates(
    snapshot: ResearchSnapshot,
    config: ResearchConfig,
) -> tuple[list[ResearchCandidate], list[tuple[str, str]]]:
    """Return ranked candidates plus row-ordered ticker rejection reasons."""
    snapshot.to_dict()
    candidates: list[ResearchCandidate] = []
    rejections: list[tuple[str, str]] = []
    for row in snapshot.rows:
        candidate, reason = _candidate_from_row(row, config)
        if candidate is not None:
            candidates.append(candidate)
            continue
        ticker = _normalize_research_ticker(row.get("ticker"))
        if ticker is None or reason is None:
            raise ValueError("validated snapshot row could not be socially screened")
        rejections.append((ticker, reason))
    return sorted(candidates, key=lambda item: (-item.score, item.ticker)), rejections


def config_as_dict(config: ResearchConfig) -> dict[str, Any]:
    """Expose the full pre-registered rule in trial reports."""
    return asdict(config)


def _candidate_from_row(
    row: dict[str, Any],
    config: ResearchConfig,
) -> tuple[ResearchCandidate | None, str | None]:
    ticker = _normalize_research_ticker(row.get("ticker"))
    if ticker is None:
        return None, "social_screen_invalid_ticker"
    try:
        buzz_score = _strict_number(row["buzz_score"])
        sentiment_score = _strict_number(row["sentiment_score"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None, "social_screen_invalid_numeric_fields"
    try:
        integer_values = (
            row["bullish_pct"],
            row["bearish_pct"],
            row["mentions"],
            row["unique_posts"],
            row["subreddit_count"],
        )
    except KeyError:
        return None, "social_screen_invalid_integer_fields"
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in integer_values
    ):
        return None, "social_screen_invalid_integer_fields"
    bullish_pct, bearish_pct, mentions, unique_posts, subreddit_count = integer_values

    spread = bullish_pct - bearish_pct
    if not math.isfinite(buzz_score) or not 0 <= buzz_score <= 100:
        return None, "social_screen_buzz_out_of_range"
    if not math.isfinite(sentiment_score) or not -1 <= sentiment_score <= 1:
        return None, "social_screen_sentiment_out_of_range"
    if (
        not 0 <= bullish_pct <= 100
        or not 0 <= bearish_pct <= 100
        or bullish_pct + bearish_pct > 100
    ):
        return None, "social_screen_invalid_sentiment_percentages"
    if min(mentions, unique_posts, subreddit_count) < 0:
        return None, "social_screen_invalid_activity_counts"
    if unique_posts > mentions or subreddit_count > unique_posts:
        return None, "social_screen_inconsistent_breadth"
    if str(row.get("trend") or "").lower() != "rising":
        return None, "social_screen_trend_not_rising"
    if sentiment_score < config.min_sentiment:
        return None, "social_screen_min_sentiment"
    if spread < config.min_bull_bear_spread:
        return None, "social_screen_min_bull_bear_spread"
    if mentions < config.min_mentions:
        return None, "social_screen_min_mentions"
    if unique_posts < config.min_unique_posts:
        return None, "social_screen_min_unique_posts"
    if subreddit_count < config.min_subreddits:
        return None, "social_screen_min_subreddits"
    if not 0 <= buzz_score < config.max_crowding_buzz:
        return None, "social_screen_max_crowding_buzz"

    try:
        direction = sentiment_score * (spread / 100)
        quality = math.log1p(unique_posts) * math.log1p(subreddit_count)
        score = direction * quality
    except (OverflowError, ValueError):
        return None, "social_screen_invalid_quality_score"
    if not math.isfinite(quality) or not math.isfinite(score):
        return None, "social_screen_invalid_quality_score"
    return (
        ResearchCandidate(
            ticker=ticker,
            score=round(score, 12),
            sentiment_score=sentiment_score,
            bull_bear_spread=spread,
            mentions=mentions,
            unique_posts=unique_posts,
            subreddit_count=subreddit_count,
            buzz_score=buzz_score,
        ),
        None,
    )


def _canonicalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Round-trip API primitives into stable JSON and reject exotic values."""
    encoded = json.dumps(row, allow_nan=False, sort_keys=True, separators=(",", ":"))
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):
        raise ValueError("Adanos row must be an object")
    return decoded


def _validate_snapshot_rows(
    rows: tuple[dict[str, Any], ...], request_limit: int
) -> None:
    if len(rows) > request_limit:
        raise ValueError("snapshot row count exceeds its request limit")
    seen: set[str] = set()
    for index, row in enumerate(rows):
        ticker = _normalize_research_ticker(row.get("ticker"))
        if ticker is None:
            raise ValueError(f"snapshot row {index} has an invalid research ticker")
        if ticker in seen:
            raise ValueError(f"snapshot rows contain duplicate ticker {ticker}")
        seen.add(ticker)


def _normalize_research_ticker(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    ticker = value.strip().upper()
    return ticker if _TICKER_RE.fullmatch(ticker) else None


def _strict_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("research numeric field must be an integer or float")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("research numeric field must be finite")
    return parsed


def _snapshot_sha256(
    *,
    schema: str,
    observed_at_utc: datetime,
    window_start: date,
    window_end: date,
    universe: str,
    request_metadata: dict[str, Any],
    rows: Iterable[dict[str, Any]],
) -> str:
    manifest = {
        "schema": schema,
        "observed_at_utc": observed_at_utc.astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z"),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "universe": universe,
        "request": request_metadata,
        "rows": list(rows),
    }
    canonical = json.dumps(
        manifest,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _parse_utc_datetime(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("observed_at_utc must be an ISO-8601 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("observed_at_utc must be timezone-aware")
    return parsed.astimezone(UTC)


def _validate_request(
    request_metadata: dict[str, Any], window_start: date, window_end: date
) -> int:
    params = request_metadata.get("params")
    base_url = request_metadata.get("base_url")
    try:
        normalized_base_url = validate_base_url(base_url)
    except ValueError as exc:
        raise ValueError("snapshot request base_url is invalid") from exc
    if (
        normalized_base_url != base_url.rstrip("/")
        or request_metadata.get("path") != "/reddit/stocks/v1/trending"
        or not isinstance(params, dict)
    ):
        raise ValueError("snapshot request metadata is incomplete")
    if "days" in params:
        raise ValueError("research snapshots must not use a live days window")
    expected = {
        "from": window_start.isoformat(),
        "to": window_end.isoformat(),
        "type": "stock",
    }
    if any(params.get(key) != value for key, value in expected.items()):
        raise ValueError("snapshot request metadata does not match its closed window")
    if set(params) != {"from", "to", "type", "limit", "offset"}:
        raise ValueError("snapshot request metadata has unexpected parameters")
    limit = params.get("limit")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("snapshot request limit must be an integer in [1, 100]")
    if params.get("offset") != 0:
        raise ValueError("v1 snapshots must capture the first trending page")
    return limit
