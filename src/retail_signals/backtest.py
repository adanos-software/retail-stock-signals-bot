"""Deterministic next-session paper backtest for Adanos research snapshots."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from functools import lru_cache
from importlib.metadata import version as package_version
from itertools import pairwise
from pathlib import Path
from typing import Any

from retail_signals import __version__
from retail_signals.research import (
    ResearchConfig,
    ResearchSnapshot,
    config_as_dict,
    load_snapshots,
    screen_research_candidates,
)

PRICE_SCHEMA_NAME = "retail-signals-price-bars-v2"
PRICE_COLUMNS = (
    "date",
    "ticker",
    "adjusted_open",
    "adjusted_close",
    "unadjusted_close",
    "unadjusted_volume",
)


@dataclass(frozen=True)
class PriceBar:
    """Daily return and point-in-time eligibility prices with explicit semantics."""

    date: date
    ticker: str
    adjusted_open: float
    adjusted_close: float
    unadjusted_close: float
    unadjusted_volume: float


@dataclass(frozen=True)
class BacktestConfig:
    """Execution and portfolio-risk assumptions exposed in every trial report."""

    holding_sessions: int = 1
    gross_exposure: float = 0.25
    max_name_weight: float = 0.05
    min_unadjusted_price: float = 5.0
    min_average_dollar_volume: float = 10_000_000.0
    liquidity_lookback: int = 20
    volatility_lookback: int = 20
    cost_bps_per_side: float = 10.0
    chronological_folds: int = 3

    def __post_init__(self) -> None:
        numeric_values = (
            self.gross_exposure,
            self.max_name_weight,
            self.min_unadjusted_price,
            self.min_average_dollar_volume,
            self.cost_bps_per_side,
        )
        if not all(math.isfinite(value) for value in numeric_values):
            raise ValueError("backtest numeric settings must be finite")
        if self.holding_sessions < 1:
            raise ValueError("holding_sessions must be positive")
        if not 0 < self.gross_exposure <= 1:
            raise ValueError("gross_exposure must be in (0, 1]")
        if not 0 < self.max_name_weight <= self.gross_exposure:
            raise ValueError("max_name_weight must be in (0, gross_exposure]")
        if self.liquidity_lookback < 2 or self.volatility_lookback < 2:
            raise ValueError("market-data lookbacks must be at least 2")
        if self.min_unadjusted_price < 0 or self.min_average_dollar_volume < 0:
            raise ValueError("price and liquidity minimums must not be negative")
        if self.cost_bps_per_side < 0:
            raise ValueError("cost_bps_per_side must not be negative")
        if self.cost_bps_per_side >= 10_000:
            raise ValueError("cost_bps_per_side must be less than 10000")
        if self.chronological_folds < 1:
            raise ValueError("chronological_folds must be positive")


@dataclass(frozen=True)
class PerformanceMetrics:
    observations: int
    total_return: float
    annualized_return: float
    annualized_volatility: float
    naive_annualized_sharpe: float | None
    max_drawdown: float
    hit_rate: float


@dataclass(frozen=True)
class PortfolioDay:
    entry_date: date
    exit_date: date
    net_return: float
    benchmark_return: float
    turnover: float
    cost: float
    nav: float
    target_weights: dict[str, float]
    realized_gross_exposure: float
    cash_weight: float
    realized_max_name_weight: float


@dataclass(frozen=True)
class AuditExclusion:
    """One deterministic reason an immutable snapshot or candidate was not used."""

    reason: str
    snapshot_sha256: str
    window_end: date
    observed_at_utc: datetime
    entry_date: date | None = None
    ticker: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "snapshot_sha256": self.snapshot_sha256,
            "window_end": self.window_end.isoformat(),
            "observed_at_utc": self.observed_at_utc.isoformat().replace("+00:00", "Z"),
            "entry_date": self.entry_date.isoformat() if self.entry_date else None,
            "ticker": self.ticker,
        }


@dataclass(frozen=True)
class FoldResult:
    start: date
    end: date
    metrics: PerformanceMetrics


@dataclass(frozen=True)
class BacktestReport:
    strategy: PerformanceMetrics
    benchmark: PerformanceMetrics
    final_nav: float
    total_turnover: float
    total_cost: float
    snapshots: int
    mapped_signal_sessions: int
    eligible_cohorts: int
    exclusions: tuple[AuditExclusion, ...]
    days: tuple[PortfolioDay, ...]
    folds: tuple[FoldResult, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready, audit-friendly trial result."""
        exclusion_counts = Counter(item.reason for item in self.exclusions)
        return {
            "status": "research_only_not_implementation_ready",
            "strategy": asdict(self.strategy),
            "benchmark": asdict(self.benchmark),
            "final_nav": self.final_nav,
            "total_turnover": self.total_turnover,
            "total_cost": self.total_cost,
            "snapshot_count": self.snapshots,
            "mapped_signal_sessions": self.mapped_signal_sessions,
            "eligible_cohorts": self.eligible_cohorts,
            "exclusion_counts": dict(sorted(exclusion_counts.items())),
            "exclusions": [item.to_dict() for item in self.exclusions],
            "folds": [
                {
                    "start": fold.start.isoformat(),
                    "end": fold.end.isoformat(),
                    "metrics": asdict(fold.metrics),
                }
                for fold in self.folds
            ],
            "days": [
                {
                    "entry_date": day.entry_date.isoformat(),
                    "exit_date": day.exit_date.isoformat(),
                    "net_return": day.net_return,
                    "benchmark_return": day.benchmark_return,
                    "turnover": day.turnover,
                    "cost": day.cost,
                    "nav": day.nav,
                    "target_weights": day.target_weights,
                    "realized_gross_exposure": day.realized_gross_exposure,
                    "cash_weight": day.cash_weight,
                    "realized_max_name_weight": day.realized_max_name_weight,
                }
                for day in self.days
            ],
        }


def load_price_bars(path: Path) -> list[PriceBar]:
    """Load the explicit return/eligibility price schema without filling gaps."""
    bars: list[PriceBar] = []
    seen: set[tuple[str, date]] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(PRICE_COLUMNS):
            raise ValueError(
                f"price CSV requires exact ordered columns: {list(PRICE_COLUMNS)}"
            )
        for line_number, row in enumerate(reader, start=2):
            try:
                if None in row:
                    raise ValueError("unexpected extra value")
                bar = PriceBar(
                    date=date.fromisoformat(row["date"]),
                    ticker=row["ticker"].strip().upper(),
                    adjusted_open=float(row["adjusted_open"]),
                    adjusted_close=float(row["adjusted_close"]),
                    unadjusted_close=float(row["unadjusted_close"]),
                    unadjusted_volume=float(row["unadjusted_volume"]),
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid price row at line {line_number}") from exc
            if not bar.ticker or not _valid_price_values(bar):
                raise ValueError(f"invalid price values at line {line_number}")
            key = (bar.ticker, bar.date)
            if key in seen:
                raise ValueError(f"duplicate price row for {bar.ticker} on {bar.date}")
            seen.add(key)
            bars.append(bar)
    return bars


def run_backtest(
    snapshots: Iterable[ResearchSnapshot],
    price_bars: Iterable[PriceBar],
    *,
    research_config: ResearchConfig | None = None,
    backtest_config: BacktestConfig | None = None,
    benchmark_ticker: str = "SPY",
) -> BacktestReport:
    """Run a long-only/cash open-to-open portfolio simulation after costs."""
    research = research_config or ResearchConfig()
    execution = backtest_config or BacktestConfig()
    snapshot_list = sorted(snapshots, key=lambda item: item.observed_at_utc)
    signal_days: set[date] = set()
    for snapshot in snapshot_list:
        snapshot.to_dict()
        if snapshot.window_end in signal_days:
            raise ValueError(
                f"multiple snapshot vintages for signal day {snapshot.window_end}"
            )
        signal_days.add(snapshot.window_end)
    bars_by_ticker = _index_bars(price_bars)
    benchmark = benchmark_ticker.upper()
    if benchmark not in bars_by_ticker:
        raise ValueError(f"benchmark ticker missing from price data: {benchmark}")

    sessions = [bar.date for bar in bars_by_ticker[benchmark]]
    if len(sessions) < 2:
        raise ValueError("benchmark requires at least two sessions")
    _validate_xnys_sessions(sessions)
    mapped, mapping_exclusions = _map_snapshots_to_sessions(
        snapshot_list,
        sessions,
        holding_sessions=execution.holding_sessions,
    )
    if not mapped:
        counts = Counter(item.reason for item in mapping_exclusions)
        raise ValueError(
            "no snapshots map to an executable next session "
            f"(exclusions={dict(sorted(counts.items()))})"
        )

    cohort_weights: dict[int, dict[str, float]] = {}
    exclusions = list(mapping_exclusions)
    for entry_index, snapshot in mapped.items():
        weights, cohort_exclusions = _build_cohort_weights(
            snapshot,
            sessions[entry_index],
            bars_by_ticker,
            sessions,
            research,
            execution,
        )
        cohort_weights[entry_index] = weights
        exclusions.extend(cohort_exclusions)

    start_index = min(mapped)
    last_entry_index = max(mapped)
    end_index = last_entry_index + execution.holding_sessions
    if end_index <= start_index:
        raise ValueError("price data does not extend beyond the final signal session")

    bar_lookup = {
        ticker: {bar.date: bar for bar in ticker_bars}
        for ticker, ticker_bars in bars_by_ticker.items()
    }
    cash = 1.0
    shares: dict[str, float] = {}
    nav = 1.0
    total_turnover = 0.0
    total_cost = 0.0
    days: list[PortfolioDay] = []
    benchmark_returns: list[float] = []
    cost_rate = execution.cost_bps_per_side / 10_000
    previous_target_weights: dict[str, float] | None = None

    for index in range(start_index, end_index):
        entry_date = sessions[index]
        exit_date = sessions[index + 1]
        current_values = _position_values(shares, entry_date, bar_lookup)
        nav_before = cash + sum(current_values.values())
        if not math.isfinite(nav_before) or nav_before <= 0:
            raise ValueError("portfolio NAV became nonpositive before rebalancing")
        target_weights = _target_weights_for_session(
            index,
            cohort_weights,
            execution,
        )
        weights_changed = previous_target_weights != target_weights
        if weights_changed:
            target_values, turnover_dollars, cost = _self_financing_targets(
                current_values=current_values,
                target_weights=target_weights,
                nav_before=nav_before,
                cost_rate=cost_rate,
            )
        else:
            # A cohort target is a buy-and-hold instruction between membership or
            # target-weight changes. Price drift is observed, not traded away.
            target_values = current_values
            turnover_dollars = 0.0
            cost = 0.0
        sell_notional = sum(
            max(current_values.get(ticker, 0.0) - target_values.get(ticker, 0.0), 0.0)
            for ticker in set(current_values) | set(target_values)
        )
        buy_notional = sum(
            max(target_values.get(ticker, 0.0) - current_values.get(ticker, 0.0), 0.0)
            for ticker in set(current_values) | set(target_values)
        )
        sell_cost = sell_notional * cost_rate
        buy_cost = buy_notional * cost_rate
        if not math.isclose(
            turnover_dollars,
            sell_notional + buy_notional,
            rel_tol=1e-12,
            abs_tol=1e-15,
        ):
            raise ValueError("transaction-cost turnover is inconsistent")
        if not math.isclose(cost, sell_cost + buy_cost, rel_tol=1e-12, abs_tol=1e-15):
            raise ValueError("transaction-cost allocation is inconsistent")

        sell_turnover = sell_notional / nav_before
        period_start_nav = nav_before - sell_cost
        if days and sell_notional > 0:
            previous = days[-1]
            previous_start_nav = previous.nav / (1 + previous.net_return)
            days[-1] = replace(
                previous,
                net_return=period_start_nav / previous_start_nav - 1,
                turnover=previous.turnover + sell_turnover,
                cost=previous.cost + sell_cost,
                nav=period_start_nav,
            )
        elif sell_notional > 1e-12:
            raise ValueError("first rebalance unexpectedly contains a sale")

        if weights_changed:
            cash = nav_before - sum(target_values.values()) - cost
            if cash < -1e-10:
                raise ValueError("self-financing rebalance produced negative cash")
            cash = max(cash, 0.0)
            shares = {
                ticker: value / _bar_for(ticker, entry_date, bar_lookup).adjusted_open
                for ticker, value in target_values.items()
                if value > 0
            }

        post_trade_values = _position_values(shares, entry_date, bar_lookup)
        post_trade_nav = cash + sum(post_trade_values.values())
        if not math.isfinite(post_trade_nav) or post_trade_nav <= 0:
            raise ValueError("portfolio NAV became nonpositive after rebalancing")
        realized_gross = sum(post_trade_values.values()) / post_trade_nav
        cash_weight = cash / post_trade_nav
        realized_max_name = (
            max(post_trade_values.values(), default=0.0) / post_trade_nav
        )
        if (
            realized_gross < -1e-12
            or cash_weight < -1e-12
            or not math.isclose(realized_gross + cash_weight, 1.0, abs_tol=1e-12)
        ):
            raise ValueError("long-only/cash exposure accounting is inconsistent")

        next_values = _position_values(shares, exit_date, bar_lookup)
        nav = cash + sum(next_values.values())
        net_return = nav / period_start_nav - 1
        benchmark_return = (
            _bar_for(benchmark, exit_date, bar_lookup).adjusted_open
            / _bar_for(benchmark, entry_date, bar_lookup).adjusted_open
            - 1
        )
        buy_turnover = buy_notional / period_start_nav
        total_turnover += sell_turnover + buy_turnover
        total_cost += cost
        benchmark_returns.append(benchmark_return)
        days.append(
            PortfolioDay(
                entry_date=entry_date,
                exit_date=exit_date,
                net_return=net_return,
                benchmark_return=benchmark_return,
                turnover=buy_turnover,
                cost=buy_cost,
                nav=nav,
                target_weights=dict(sorted(target_weights.items())),
                realized_gross_exposure=realized_gross,
                cash_weight=cash_weight,
                realized_max_name_weight=realized_max_name,
            )
        )
        previous_target_weights = target_weights

    final_values = _position_values(shares, sessions[end_index], bar_lookup)
    liquidation_notional = sum(final_values.values())
    liquidation_cost = liquidation_notional * execution.cost_bps_per_side / 10_000
    liquidation_turnover = liquidation_notional / nav if nav > 0 else 0.0
    nav -= liquidation_cost
    if not math.isfinite(nav) or nav <= 0:
        raise ValueError("portfolio NAV became nonpositive after liquidation")
    last_day = days[-1]
    last_period_start_nav = last_day.nav / (1 + last_day.net_return)
    days[-1] = replace(
        last_day,
        net_return=nav / last_period_start_nav - 1,
        turnover=last_day.turnover + liquidation_turnover,
        cost=last_day.cost + liquidation_cost,
        nav=nav,
    )
    total_turnover += liquidation_turnover
    total_cost += liquidation_cost

    returns = [day.net_return for day in days]
    strategy_metrics = _performance_metrics(returns, final_nav=nav)
    benchmark_metrics = _performance_metrics(
        benchmark_returns,
        final_nav=math.prod(1 + value for value in benchmark_returns),
    )
    folds = _chronological_folds(days, execution.chronological_folds)
    return BacktestReport(
        strategy=strategy_metrics,
        benchmark=benchmark_metrics,
        final_nav=nav,
        total_turnover=total_turnover,
        total_cost=total_cost,
        snapshots=len(snapshot_list),
        mapped_signal_sessions=len(mapped),
        eligible_cohorts=sum(bool(weights) for weights in cohort_weights.values()),
        exclusions=tuple(exclusions),
        days=tuple(days),
        folds=tuple(folds),
    )


def main(argv: list[str] | None = None) -> int:
    """Run one trial from immutable snapshots and explicit research price bars."""
    args = _parse_args(argv)
    try:
        return _run_cli(args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _run_cli(args: argparse.Namespace) -> int:
    """Execute a parsed trial while leaving argparse responsible for usage errors."""
    snapshot_paths = [Path(value) for value in args.snapshots]
    price_path = Path(args.prices)
    output_path = Path(args.output)
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite trial report: {output_path}")

    snapshot_hashes = [_file_sha256(path) for path in snapshot_paths]
    price_hash = _file_sha256(price_path)

    research_config = ResearchConfig(
        min_sentiment=args.min_sentiment,
        max_crowding_buzz=args.max_crowding_buzz,
    )
    backtest_config = BacktestConfig(
        holding_sessions=args.holding_sessions,
        gross_exposure=args.gross_exposure,
        max_name_weight=args.max_name_weight,
        min_unadjusted_price=args.min_unadjusted_price,
        min_average_dollar_volume=args.min_average_dollar_volume,
        cost_bps_per_side=args.cost_bps_per_side,
        chronological_folds=args.chronological_folds,
    )
    report = run_backtest(
        load_snapshots(snapshot_paths),
        load_price_bars(price_path),
        research_config=research_config,
        backtest_config=backtest_config,
        benchmark_ticker=args.benchmark,
    )
    if snapshot_hashes != [_file_sha256(path) for path in snapshot_paths]:
        raise RuntimeError("snapshot input changed while the trial was running")
    if price_hash != _file_sha256(price_path):
        raise RuntimeError("price input changed while the trial was running")
    payload = report.to_dict()
    payload["trial"] = {
        "created_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "retail_signals_version": __version__,
        "snapshot_files": [
            {"path": str(path), "sha256": content_hash}
            for path, content_hash in zip(snapshot_paths, snapshot_hashes, strict=True)
        ],
        "price_file": {"path": str(price_path), "sha256": price_hash},
        "price_schema": {
            "name": PRICE_SCHEMA_NAME,
            "columns": list(PRICE_COLUMNS),
            "return_fields": ["adjusted_open", "adjusted_close"],
            "point_in_time_eligibility_fields": [
                "unadjusted_close",
                "unadjusted_volume",
            ],
        },
        "research_config": config_as_dict(research_config),
        "backtest_config": asdict(backtest_config),
        "benchmark": args.benchmark.upper(),
        "exchange_calendar": {
            "name": "XNYS",
            "exchange_calendars_version": package_version("exchange-calendars"),
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output_path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except FileExistsError as exc:
        raise FileExistsError(
            f"refusing to overwrite trial report: {output_path}"
        ) from exc
    print(
        f"Wrote {output_path}: net return {report.strategy.total_return:.2%}, "
        f"max drawdown {report.strategy.max_drawdown:.2%}, "
        f"turnover {report.total_turnover:.2f}x"
    )
    return 0


def _index_bars(price_bars: Iterable[PriceBar]) -> dict[str, list[PriceBar]]:
    indexed: dict[str, list[PriceBar]] = {}
    seen: set[tuple[str, date]] = set()
    for bar in price_bars:
        ticker = bar.ticker.strip().upper()
        if not ticker:
            raise ValueError(f"price bar has an empty ticker on {bar.date}")
        key = (ticker, bar.date)
        if key in seen:
            raise ValueError(f"duplicate price bar for {ticker} on {bar.date}")
        if not _valid_price_values(bar):
            raise ValueError(f"invalid price bar for {ticker} on {bar.date}")
        seen.add(key)
        indexed.setdefault(ticker, []).append(
            PriceBar(
                bar.date,
                ticker,
                bar.adjusted_open,
                bar.adjusted_close,
                bar.unadjusted_close,
                bar.unadjusted_volume,
            )
        )
    for bars in indexed.values():
        bars.sort(key=lambda item: item.date)
    return indexed


def _map_snapshots_to_sessions(
    snapshots: list[ResearchSnapshot],
    sessions: list[date],
    *,
    holding_sessions: int,
) -> tuple[dict[int, ResearchSnapshot], list[AuditExclusion]]:
    """Map snapshots while keeping the latest as-of view for each XNYS open.

    Several closed calendar days can map to one exchange open. The most recently
    completed response is the deliberate decision view; every older view remains
    visible in the audit trail as superseded.
    """
    mapped: dict[int, ResearchSnapshot] = {}
    exclusions: list[AuditExclusion] = []
    executable_entries = range(max(0, len(sessions) - holding_sessions))
    for snapshot in snapshots:
        if _xnys_open_utc(sessions[0]) > snapshot.observed_at_utc:
            possible_earlier_entries = [
                session
                for session in _xnys_sessions_between(
                    snapshot.observed_at_utc.date(), sessions[0]
                )
                if _xnys_open_utc(session) > snapshot.observed_at_utc
            ]
            if possible_earlier_entries and possible_earlier_entries[0] != sessions[0]:
                raise ValueError(
                    "benchmark price data starts after the first executable XNYS session"
                )
        entry_index = next(
            (
                index
                for index in executable_entries
                if _xnys_open_utc(sessions[index]) > snapshot.observed_at_utc
            ),
            None,
        )
        if entry_index is None:
            exclusions.append(
                _audit_exclusion(snapshot, "right_censored_holding_horizon")
            )
            continue
        existing = mapped.get(entry_index)
        if existing is None:
            mapped[entry_index] = snapshot
            continue
        entry_date = sessions[entry_index]
        if snapshot.observed_at_utc > existing.observed_at_utc:
            exclusions.append(
                _audit_exclusion(
                    existing,
                    "superseded_by_later_snapshot_for_same_entry",
                    entry_date=entry_date,
                )
            )
            mapped[entry_index] = snapshot
        else:
            exclusions.append(
                _audit_exclusion(
                    snapshot,
                    "superseded_by_later_snapshot_for_same_entry",
                    entry_date=entry_date,
                )
            )
    return mapped, exclusions


def _audit_exclusion(
    snapshot: ResearchSnapshot,
    reason: str,
    *,
    entry_date: date | None = None,
    ticker: str | None = None,
) -> AuditExclusion:
    return AuditExclusion(
        reason=reason,
        snapshot_sha256=snapshot.content_sha256,
        window_end=snapshot.window_end,
        observed_at_utc=snapshot.observed_at_utc,
        entry_date=entry_date,
        ticker=ticker,
    )


def _build_cohort_weights(
    snapshot: ResearchSnapshot,
    entry_date: date,
    bars_by_ticker: dict[str, list[PriceBar]],
    market_sessions: list[date],
    research: ResearchConfig,
    execution: BacktestConfig,
) -> tuple[dict[str, float], list[AuditExclusion]]:
    ranked: list[tuple[str, float]] = []
    social_candidates, social_rejections = screen_research_candidates(
        snapshot, research
    )
    exclusions = [
        _audit_exclusion(
            snapshot,
            reason,
            entry_date=entry_date,
            ticker=ticker,
        )
        for ticker, reason in social_rejections
    ]
    if not social_candidates:
        if not social_rejections:
            exclusions.append(
                _audit_exclusion(
                    snapshot,
                    "no_social_candidates",
                    entry_date=entry_date,
                )
            )
        return {}, exclusions

    for candidate in social_candidates:
        if len(ranked) == research.max_candidates:
            exclusions.append(
                _audit_exclusion(
                    snapshot,
                    "portfolio_candidate_limit",
                    entry_date=entry_date,
                    ticker=candidate.ticker,
                )
            )
            continue
        bars = bars_by_ticker.get(candidate.ticker)
        if not bars:
            exclusions.append(
                _audit_exclusion(
                    snapshot,
                    "market_gate_missing_ticker_prices",
                    entry_date=entry_date,
                    ticker=candidate.ticker,
                )
            )
            continue
        market, market_reason = _market_stats(
            bars, entry_date, market_sessions, execution
        )
        if market is None:
            exclusions.append(
                _audit_exclusion(
                    snapshot,
                    market_reason or "market_gate_invalid_stats",
                    entry_date=entry_date,
                    ticker=candidate.ticker,
                )
            )
            continue
        volatility, prior_unadjusted_close, average_dollar_volume = market
        if prior_unadjusted_close < execution.min_unadjusted_price:
            exclusions.append(
                _audit_exclusion(
                    snapshot,
                    "market_gate_min_unadjusted_price",
                    entry_date=entry_date,
                    ticker=candidate.ticker,
                )
            )
            continue
        if average_dollar_volume < execution.min_average_dollar_volume:
            exclusions.append(
                _audit_exclusion(
                    snapshot,
                    "market_gate_min_average_dollar_volume",
                    entry_date=entry_date,
                    ticker=candidate.ticker,
                )
            )
            continue
        risk_adjusted_score = candidate.score / volatility
        if math.isfinite(risk_adjusted_score) and risk_adjusted_score > 0:
            ranked.append((candidate.ticker, risk_adjusted_score))

    if not ranked:
        return {}, exclusions
    cohort_budget = execution.gross_exposure / execution.holding_sessions
    score_sum = sum(score for _, score in ranked)
    return (
        {
            ticker: min(cohort_budget * score / score_sum, execution.max_name_weight)
            for ticker, score in ranked
        },
        exclusions,
    )


def _market_stats(
    bars: list[PriceBar],
    entry_date: date,
    market_sessions: list[date],
    config: BacktestConfig,
) -> tuple[tuple[float, float, float] | None, str | None]:
    needed = max(config.liquidity_lookback, config.volatility_lookback + 1)
    expected_dates = [session for session in market_sessions if session < entry_date][
        -needed:
    ]
    if len(expected_dates) < needed:
        return None, "market_gate_insufficient_lookback"
    bars_by_date = {bar.date: bar for bar in bars}
    if any(session not in bars_by_date for session in expected_dates):
        return None, "market_gate_missing_lookback_bar"
    prior = [bars_by_date[session] for session in expected_dates]
    liquidity_window = prior[-config.liquidity_lookback :]
    volatility_window = prior[-(config.volatility_lookback + 1) :]
    returns = [
        current.adjusted_close / previous.adjusted_close - 1
        for previous, current in pairwise(volatility_window)
    ]
    volatility = statistics.stdev(returns) * math.sqrt(252)
    if not math.isfinite(volatility) or volatility <= 0:
        return None, "market_gate_invalid_trailing_volatility"
    average_dollar_volume = statistics.fmean(
        bar.unadjusted_close * bar.unadjusted_volume for bar in liquidity_window
    )
    if not math.isfinite(average_dollar_volume):
        return None, "market_gate_invalid_average_dollar_volume"
    return (
        volatility,
        prior[-1].unadjusted_close,
        average_dollar_volume,
    ), None


def _target_weights_for_session(
    session_index: int,
    cohorts: dict[int, dict[str, float]],
    config: BacktestConfig,
) -> dict[str, float]:
    combined: dict[str, float] = {}
    for entry_index, weights in cohorts.items():
        if entry_index <= session_index < entry_index + config.holding_sessions:
            for ticker, weight in weights.items():
                combined[ticker] = min(
                    combined.get(ticker, 0.0) + weight,
                    config.max_name_weight,
                )
    return combined


def _self_financing_targets(
    *,
    current_values: dict[str, float],
    target_weights: dict[str, float],
    nav_before: float,
    cost_rate: float,
) -> tuple[dict[str, float], float, float]:
    """Size target weights on post-cost NAV so fees never require borrowing."""

    def values_and_turnover(post_cost_nav: float) -> tuple[dict[str, float], float]:
        values = {
            ticker: post_cost_nav * weight for ticker, weight in target_weights.items()
        }
        tickers = set(current_values) | set(values)
        turnover = sum(
            abs(values.get(ticker, 0.0) - current_values.get(ticker, 0.0))
            for ticker in tickers
        )
        return values, turnover

    if cost_rate == 0:
        target_values, turnover = values_and_turnover(nav_before)
        return target_values, turnover, 0.0

    low = 0.0
    high = nav_before
    for _ in range(80):
        post_cost_nav = (low + high) / 2
        _, turnover = values_and_turnover(post_cost_nav)
        if post_cost_nav + cost_rate * turnover > nav_before:
            high = post_cost_nav
        else:
            low = post_cost_nav

    post_cost_nav = (low + high) / 2
    target_values, turnover = values_and_turnover(post_cost_nav)
    cost = turnover * cost_rate
    return target_values, turnover, cost


def _position_values(
    shares: dict[str, float],
    session: date,
    lookup: dict[str, dict[date, PriceBar]],
) -> dict[str, float]:
    return {
        ticker: units * _bar_for(ticker, session, lookup).adjusted_open
        for ticker, units in shares.items()
    }


def _bar_for(
    ticker: str,
    session: date,
    lookup: dict[str, dict[date, PriceBar]],
) -> PriceBar:
    try:
        return lookup[ticker][session]
    except KeyError as exc:
        raise ValueError(
            f"missing price for held ticker {ticker} on {session}"
        ) from exc


def _performance_metrics(
    returns: list[float],
    *,
    final_nav: float | None = None,
) -> PerformanceMetrics:
    if not returns:
        return PerformanceMetrics(0, 0.0, 0.0, 0.0, None, 0.0, 0.0)
    compounded_nav = (
        final_nav
        if final_nav is not None
        else math.prod(1 + value for value in returns)
    )
    total_return = compounded_nav - 1
    annualized_return = (
        compounded_nav ** (252 / len(returns)) - 1 if compounded_nav > 0 else -1.0
    )
    volatility = statistics.stdev(returns) * math.sqrt(252) if len(returns) > 1 else 0.0
    naive_sharpe = (
        statistics.fmean(returns) / statistics.stdev(returns) * math.sqrt(252)
        if len(returns) > 1 and statistics.stdev(returns) > 0
        else None
    )
    nav = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in returns:
        nav *= 1 + value
        peak = max(peak, nav)
        max_drawdown = min(max_drawdown, nav / peak - 1)
    if final_nav is not None:
        max_drawdown = min(max_drawdown, final_nav / peak - 1)
    return PerformanceMetrics(
        observations=len(returns),
        total_return=total_return,
        annualized_return=annualized_return,
        annualized_volatility=volatility,
        naive_annualized_sharpe=naive_sharpe,
        max_drawdown=max_drawdown,
        hit_rate=sum(value > 0 for value in returns) / len(returns),
    )


def _chronological_folds(days: list[PortfolioDay], count: int) -> list[FoldResult]:
    if not days:
        return []
    fold_count = min(count, len(days))
    base, remainder = divmod(len(days), fold_count)
    folds: list[FoldResult] = []
    start = 0
    for index in range(fold_count):
        size = base + (1 if index < remainder else 0)
        chunk = days[start : start + size]
        returns = [day.net_return for day in chunk]
        folds.append(
            FoldResult(
                start=chunk[0].entry_date,
                end=chunk[-1].exit_date,
                metrics=_performance_metrics(returns),
            )
        )
        start += size
    return folds


@lru_cache(maxsize=1)
def _xnys_calendar() -> Any:
    try:
        import exchange_calendars
    except ModuleNotFoundError as exc:
        raise ValueError(
            'the research backtest requires `pip install ".[research]"`'
        ) from exc
    return exchange_calendars.get_calendar("XNYS")


def _xnys_sessions_between(start: date, end: date) -> list[date]:
    try:
        return [
            session.date() for session in _xnys_calendar().sessions_in_range(start, end)
        ]
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"XNYS calendar does not cover {start} through {end}") from exc


def _validate_xnys_sessions(sessions: list[date]) -> None:
    expected = _xnys_sessions_between(sessions[0], sessions[-1])
    if sessions == expected:
        return
    missing = sorted(set(expected) - set(sessions))
    unexpected = sorted(set(sessions) - set(expected))
    details = []
    if missing:
        details.append(
            f"missing={','.join(value.isoformat() for value in missing[:5])}"
        )
    if unexpected:
        details.append(
            f"unexpected={','.join(value.isoformat() for value in unexpected[:5])}"
        )
    raise ValueError(f"benchmark XNYS calendar mismatch ({'; '.join(details)})")


def _xnys_open_utc(session: date) -> datetime:
    return _xnys_calendar().session_open(session).to_pydatetime().astimezone(UTC)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_price_values(bar: PriceBar) -> bool:
    prices = (bar.adjusted_open, bar.adjusted_close, bar.unadjusted_close)
    return (
        all(math.isfinite(value) and value > 0 for value in prices)
        and math.isfinite(bar.unadjusted_volume)
        and bar.unadjusted_volume >= 0
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a point-in-time, next-session Adanos sentiment paper backtest."
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--snapshots", nargs="+", required=True)
    parser.add_argument(
        "--prices",
        required=True,
        help=(
            "CSV with adjusted return prices and point-in-time unadjusted "
            "eligibility fields"
        ),
    )
    parser.add_argument("--output", required=True, help="New JSON trial-report path.")
    parser.add_argument("--benchmark", default="SPY")
    parser.add_argument("--holding-sessions", type=int, default=1, choices=(1, 5, 20))
    parser.add_argument("--gross-exposure", type=float, default=0.25)
    parser.add_argument("--max-name-weight", type=float, default=0.05)
    parser.add_argument("--min-unadjusted-price", type=float, default=5.0)
    parser.add_argument("--min-average-dollar-volume", type=float, default=10_000_000.0)
    parser.add_argument("--cost-bps-per-side", type=float, default=10.0)
    parser.add_argument("--chronological-folds", type=int, default=3)
    parser.add_argument("--min-sentiment", type=float, default=0.05)
    parser.add_argument("--max-crowding-buzz", type=float, default=85.0)
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
