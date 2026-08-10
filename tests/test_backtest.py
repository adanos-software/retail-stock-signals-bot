import json
import math
from datetime import UTC, date, datetime, timedelta

import pytest

from retail_signals import __version__
from retail_signals.backtest import (
    PRICE_COLUMNS,
    PRICE_SCHEMA_NAME,
    BacktestConfig,
    PriceBar,
    _self_financing_targets,
    _xnys_sessions_between,
    load_price_bars,
    run_backtest,
)
from retail_signals.backtest import (
    main as backtest_main,
)
from retail_signals.research import capture_closed_snapshot, write_snapshot


def test_backtest_enters_only_after_observation_at_next_session_open():
    sessions = _weekdays(date(2026, 1, 5), 8)
    snapshots = [_snapshot(sessions[3], 22, [_row("AAA")])]
    bars = [
        *_bars("SPY", sessions, [100.0] * len(sessions)),
        *_bars("AAA", sessions, [80, 90, 95, 50, 100, 110, 111, 112]),
    ]

    report = run_backtest(
        snapshots,
        bars,
        backtest_config=_config(cost_bps_per_side=0),
    )

    assert report.days[0].entry_date == sessions[4]
    assert report.days[0].exit_date == sessions[5]
    assert report.days[0].target_weights == {"AAA": 1.0}
    assert report.strategy.total_return == pytest.approx(0.10)
    assert report.benchmark.total_return == pytest.approx(0.0)


def test_backtest_charges_entry_and_final_liquidation_costs():
    sessions = _weekdays(date(2026, 1, 5), 8)
    snapshot = _snapshot(sessions[3], 22, [_row("AAA")])
    bars = [
        *_bars("SPY", sessions, [100.0] * len(sessions)),
        *_bars("AAA", sessions, [80, 90, 95, 50, 100, 110, 111, 112]),
    ]

    no_cost = run_backtest(
        [snapshot],
        bars,
        backtest_config=_config(
            gross_exposure=0.99,
            max_name_weight=0.99,
            cost_bps_per_side=0,
        ),
    )
    with_cost = run_backtest(
        [snapshot],
        bars,
        backtest_config=_config(
            gross_exposure=0.99,
            max_name_weight=0.99,
            cost_bps_per_side=10,
        ),
    )

    cost_rate = 10 / 10_000
    post_cost_nav = 1 / (1 + 0.99 * cost_rate)
    entry_notional = post_cost_nav * 0.99
    entry_cost = entry_notional * cost_rate
    exit_notional = entry_notional * 1.10
    liquidation_cost = exit_notional * cost_rate
    expected_final_nav = (
        post_cost_nav - entry_notional + exit_notional - liquidation_cost
    )

    assert with_cost.final_nav < no_cost.final_nav
    assert with_cost.total_cost == pytest.approx(entry_cost + liquidation_cost)
    assert with_cost.final_nav == pytest.approx(expected_final_nav)
    assert with_cost.strategy.total_return == pytest.approx(expected_final_nav - 1)
    assert with_cost.days[-1].net_return == pytest.approx(
        with_cost.strategy.total_return
    )
    assert with_cost.days[-1].cost == pytest.approx(with_cost.total_cost)
    assert with_cost.days[-1].nav == pytest.approx(with_cost.final_nav)
    assert sum(day.turnover for day in with_cost.days) == pytest.approx(
        with_cost.total_turnover
    )


def test_backtest_reserves_costs_at_full_gross_exposure():
    sessions = _weekdays(date(2026, 1, 5), 8)
    snapshot = _snapshot(sessions[3], 22, [_row("AAA")])
    bars = [
        *_bars("SPY", sessions, [100.0] * len(sessions)),
        *_bars("AAA", sessions, [80, 90, 95, 50, 100, 110, 111, 112]),
    ]

    report = run_backtest(
        [snapshot],
        bars,
        backtest_config=_config(cost_bps_per_side=10),
    )

    cost_rate = 10 / 10_000
    entry_notional = 1 / (1 + cost_rate)
    expected_final_nav = entry_notional * 1.10 * (1 - cost_rate)
    assert report.days[0].target_weights == {"AAA": 1.0}
    assert report.final_nav == pytest.approx(expected_final_nav)


def test_backtest_rejects_cost_of_one_hundred_percent_per_side():
    with pytest.raises(ValueError, match="less than 10000"):
        _config(cost_bps_per_side=10_000)


def test_self_financing_rebalance_keeps_post_cost_weight_cap():
    targets, turnover, cost = _self_financing_targets(
        current_values={"AAA": 1.0},
        target_weights={"BBB": 1.0},
        nav_before=1.0,
        cost_rate=0.001,
    )

    post_cost_nav = 1.0 - cost
    assert targets["BBB"] / post_cost_nav == pytest.approx(1.0)
    assert turnover == pytest.approx(1.0 + targets["BBB"])
    assert post_cost_nav - targets["BBB"] == pytest.approx(0.0, abs=1e-12)


def test_exit_cost_stays_with_trade_when_a_later_signal_is_added():
    sessions = _weekdays(date(2026, 1, 5), 10)
    first = _snapshot(sessions[3], 22, [_row("AAA")])
    later = _snapshot(sessions[4], 22, [_row("BBB")])
    bars = [
        *_bars("SPY", sessions, [100.0] * len(sessions)),
        *_bars("AAA", sessions, [100, 101, 99, 100, 100, 110, 110, 110, 110, 110]),
        *_bars("BBB", sessions, [100.0] * len(sessions)),
    ]
    config = _config(cost_bps_per_side=10)

    standalone = run_backtest([first], bars, backtest_config=config)
    extended = run_backtest([first, later], bars, backtest_config=config)

    assert extended.days[0].net_return == pytest.approx(standalone.days[0].net_return)
    assert extended.days[0].cost == pytest.approx(standalone.days[0].cost)
    assert extended.days[0].turnover == pytest.approx(standalone.days[0].turnover)
    assert extended.days[0].nav == pytest.approx(standalone.days[0].nav)
    assert math.prod(1 + day.net_return for day in extended.days) == pytest.approx(
        extended.final_nav
    )
    assert sum(day.cost for day in extended.days) == pytest.approx(extended.total_cost)
    assert sum(day.turnover for day in extended.days) == pytest.approx(
        extended.total_turnover
    )


def test_price_loader_rejects_nonfinite_values(tmp_path):
    price_path = tmp_path / "prices.csv"
    price_path.write_text(
        ",".join(PRICE_COLUMNS) + "\n2026-01-05,SPY,nan,100,100,1000\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid price values"):
        load_price_bars(price_path)


def test_price_loader_rejects_ambiguous_legacy_schema(tmp_path):
    price_path = tmp_path / "prices.csv"
    price_path.write_text(
        "date,ticker,open,close,volume\n2026-01-05,SPY,100,100,1000\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="exact ordered columns"):
        load_price_bars(price_path)


def test_weekend_snapshots_map_once_and_latest_snapshot_wins():
    sessions = [
        date(2026, 8, 5),
        date(2026, 8, 6),
        date(2026, 8, 7),
        date(2026, 8, 10),
        date(2026, 8, 11),
    ]
    saturday = _snapshot(date(2026, 8, 8), 10, [_row("AAA")])
    sunday = _snapshot(date(2026, 8, 9), 10, [_row("BBB")])
    bars = [
        *_bars("SPY", sessions, [100] * len(sessions)),
        *_bars("AAA", sessions, [100, 101, 99, 100, 101]),
        *_bars("BBB", sessions, [100, 98, 102, 100, 102]),
    ]

    report = run_backtest(
        [saturday, sunday],
        bars,
        backtest_config=_config(cost_bps_per_side=0),
    )

    assert report.mapped_signal_sessions == 1
    assert report.days[0].entry_date == date(2026, 8, 10)
    assert report.days[0].target_weights == {"BBB": 1.0}
    assert [item.reason for item in report.exclusions] == [
        "superseded_by_later_snapshot_for_same_entry"
    ]
    assert report.exclusions[0].snapshot_sha256 == saturday.content_sha256
    assert report.exclusions[0].entry_date == date(2026, 8, 10)


def test_backtest_rejects_duplicate_vintages_for_one_signal_day():
    sessions = _weekdays(date(2026, 1, 5), 8)
    first = _snapshot(sessions[3], 12, [_row("AAA")])
    second = _snapshot(sessions[3], 22, [_row("AAA")])
    bars = [
        *_bars("SPY", sessions, [100.0] * len(sessions)),
        *_bars("AAA", sessions, [100.0] * len(sessions)),
    ]

    with pytest.raises(ValueError, match="multiple snapshot vintages"):
        run_backtest(
            [first, second],
            bars,
            backtest_config=_config(cost_bps_per_side=0),
        )


def test_backtest_does_not_shorten_holding_period_at_price_data_edge():
    sessions = _weekdays(date(2026, 1, 5), 8)
    snapshot = _snapshot(sessions[3], 22, [_row("AAA")])
    bars = [
        *_bars("SPY", sessions, [100.0] * len(sessions)),
        *_bars("AAA", sessions, [100.0] * len(sessions)),
    ]

    with pytest.raises(ValueError, match="no snapshots map"):
        run_backtest(
            [snapshot],
            bars,
            backtest_config=_config(
                holding_sessions=5,
                cost_bps_per_side=0,
            ),
        )


def test_backtest_audits_right_censored_snapshot_when_earlier_trial_runs():
    sessions = _weekdays(date(2026, 1, 5), 12)
    executable = _snapshot(sessions[3], 22, [_row("AAA")])
    censored = _snapshot(sessions[9], 22, [_row("AAA")])
    bars = [
        *_bars("SPY", sessions, [100.0] * len(sessions)),
        *_bars("AAA", sessions, [100.0] * len(sessions)),
    ]

    report = run_backtest(
        [executable, censored],
        bars,
        backtest_config=_config(holding_sessions=5, cost_bps_per_side=0),
    )

    assert report.snapshots == 2
    assert report.mapped_signal_sessions == 1
    assert [item.reason for item in report.exclusions] == [
        "right_censored_holding_horizon"
    ]
    assert report.exclusions[0].snapshot_sha256 == censored.content_sha256
    assert report.to_dict()["exclusion_counts"] == {"right_censored_holding_horizon": 1}


def test_backtest_audits_snapshot_with_no_social_candidates():
    sessions = _weekdays(date(2026, 1, 5), 8)
    snapshot = _snapshot(sessions[3], 22, [])

    report = run_backtest(
        [snapshot],
        _bars("SPY", sessions, [100.0] * len(sessions)),
        backtest_config=_config(cost_bps_per_side=0),
    )

    assert report.eligible_cohorts == 0
    assert report.days[0].realized_gross_exposure == 0
    assert report.days[0].cash_weight == 1
    assert [item.reason for item in report.exclusions] == ["no_social_candidates"]


def test_backtest_audits_each_social_rejection_without_blanket_duplicate():
    sessions = _weekdays(date(2026, 1, 5), 8)
    falling = _row("FALL")
    falling["trend"] = "falling"
    thin = _row("THIN")
    thin.update(mentions=3, unique_posts=1, subreddit_count=1)
    snapshot = _snapshot(
        sessions[3],
        22,
        [falling, thin],
    )

    report = run_backtest(
        [snapshot],
        _bars("SPY", sessions, [100.0] * len(sessions)),
        backtest_config=_config(cost_bps_per_side=0),
    )

    assert report.eligible_cohorts == 0
    assert [(item.ticker, item.reason) for item in report.exclusions] == [
        ("FALL", "social_screen_trend_not_rising"),
        ("THIN", "social_screen_min_mentions"),
    ]
    assert "no_social_candidates" not in report.to_dict()["exclusion_counts"]


def test_backtest_rejects_a_missing_benchmark_exchange_session():
    sessions = _weekdays(date(2026, 1, 5), 8)
    snapshot = _snapshot(sessions[3], 22, [_row("AAA")])
    benchmark_bars = [
        bar
        for bar in _bars("SPY", sessions, [100.0] * len(sessions))
        if bar.date != sessions[4]
    ]
    bars = [
        *benchmark_bars,
        *_bars("AAA", sessions, [100.0] * len(sessions)),
    ]

    with pytest.raises(ValueError, match="benchmark XNYS calendar mismatch"):
        run_backtest(
            [snapshot],
            bars,
            backtest_config=_config(cost_bps_per_side=0),
        )


def test_liquidity_gate_uses_only_bars_before_entry():
    sessions = _weekdays(date(2026, 1, 5), 8)
    snapshot = _snapshot(sessions[3], 22, [_row("AAA")])
    low_then_high_volume = [1, 1, 1, 1, 1_000_000_000, 1_000_000_000, 1, 1]
    bars = [
        *_bars("SPY", sessions, [100] * len(sessions)),
        *_bars(
            "AAA",
            sessions,
            [100, 101, 99, 100, 100, 110, 111, 112],
            volumes=low_then_high_volume,
        ),
    ]

    report = run_backtest(
        [snapshot],
        bars,
        backtest_config=_config(
            cost_bps_per_side=0,
            min_average_dollar_volume=1_000,
        ),
    )

    assert report.eligible_cohorts == 0
    assert report.days[0].target_weights == {}
    assert report.strategy.total_return == 0
    assert [item.reason for item in report.exclusions] == [
        "market_gate_min_average_dollar_volume"
    ]


def test_market_gates_run_before_top_candidate_truncation():
    sessions = _weekdays(date(2026, 1, 5), 8)
    rows = []
    for index, ticker in enumerate(("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")):
        row = _row(ticker)
        row["unique_posts"] = 20 - index
        rows.append(row)
    snapshot = _snapshot(sessions[3], 22, rows)
    bars = [*_bars("SPY", sessions, [100.0] * len(sessions))]
    for ticker in ("BBB", "CCC", "DDD", "EEE", "FFF"):
        bars.extend(_bars(ticker, sessions, [100.0] * len(sessions)))

    report = run_backtest(
        [snapshot],
        bars,
        backtest_config=_config(cost_bps_per_side=0),
    )

    assert set(report.days[0].target_weights) == {"BBB", "CCC", "DDD", "EEE", "FFF"}


def test_market_stats_reject_stale_history_with_a_missing_benchmark_session():
    sessions = _weekdays(date(2026, 1, 5), 8)
    snapshot = _snapshot(sessions[3], 22, [_row("AAA")])
    candidate_bars = [
        bar
        for bar in _bars("AAA", sessions, [100.0] * len(sessions))
        if bar.date != sessions[3]
    ]
    bars = [
        *_bars("SPY", sessions, [100.0] * len(sessions)),
        *candidate_bars,
    ]

    report = run_backtest(
        [snapshot],
        bars,
        backtest_config=_config(cost_bps_per_side=0),
    )

    assert report.eligible_cohorts == 0
    assert report.days[0].target_weights == {}
    assert [item.reason for item in report.exclusions] == [
        "market_gate_missing_lookback_bar"
    ]


def test_return_adjustment_scale_does_not_change_point_in_time_gates_or_returns():
    sessions = _weekdays(date(2026, 1, 5), 8)
    snapshot = _snapshot(sessions[3], 22, [_row("AAA")])
    opens = [80, 90, 95, 50, 100, 110, 111, 112]
    config = _config(
        cost_bps_per_side=0,
        min_unadjusted_price=60,
        min_average_dollar_volume=50_000_000,
    )
    benchmark = _bars("SPY", sessions, [100.0] * len(sessions))

    unscaled = run_backtest(
        [snapshot],
        [
            *benchmark,
            *_bars("AAA", sessions, opens, unadjusted_closes=[100.0] * len(sessions)),
        ],
        backtest_config=config,
    )
    retrospectively_split_scaled = run_backtest(
        [snapshot],
        [
            *benchmark,
            *_bars(
                "AAA",
                sessions,
                opens,
                adjusted_scale=0.05,
                unadjusted_closes=[100.0] * len(sessions),
            ),
        ],
        backtest_config=config,
    )

    assert unscaled.eligible_cohorts == 1
    assert retrospectively_split_scaled.eligible_cohorts == 1
    assert retrospectively_split_scaled.days[0].target_weights == pytest.approx(
        unscaled.days[0].target_weights
    )
    assert retrospectively_split_scaled.final_nav == pytest.approx(unscaled.final_nav)


@pytest.mark.parametrize("holding_sessions", [5, 20])
def test_unchanged_multisession_target_carries_shares_without_daily_churn(
    holding_sessions,
):
    sessions = _weekdays(date(2026, 1, 5), 55)
    observed_index = 24
    entry_index = observed_index + 1
    snapshot = _snapshot(sessions[observed_index], 22, [_row("AAA")])
    opens = [100.0] * len(sessions)
    opens[entry_index + 1 :] = [200.0] * (len(sessions) - entry_index - 1)
    report = run_backtest(
        [snapshot],
        [
            *_bars("SPY", sessions, [100.0] * len(sessions)),
            *_bars("AAA", sessions, opens),
        ],
        backtest_config=_config(
            holding_sessions=holding_sessions,
            cost_bps_per_side=10,
        ),
    )

    cohort_weight = 1 / holding_sessions
    assert report.days[0].turnover == pytest.approx(
        cohort_weight / (1 + cohort_weight * 0.001)
    )
    assert report.days[1].turnover == 0
    assert report.days[1].cost == 0
    assert report.days[1].realized_gross_exposure > cohort_weight
    assert all(day.turnover == 0 for day in report.days[1:-1])
    assert all(day.cost == 0 for day in report.days[1:-1])
    _assert_portfolio_identities(report)


def test_twenty_session_overlap_rebalances_only_when_combined_target_changes():
    sessions = _weekdays(date(2026, 1, 5), 60)
    first_index = 24
    snapshots = [
        _snapshot(sessions[first_index], 22, [_row("AAA")]),
        _snapshot(sessions[first_index + 1], 22, [_row("BBB")]),
    ]
    aaa_opens = [100.0] * len(sessions)
    aaa_opens[first_index + 3 :] = [120.0] * (len(sessions) - first_index - 3)
    report = run_backtest(
        snapshots,
        [
            *_bars("SPY", sessions, [100.0] * len(sessions)),
            *_bars("AAA", sessions, aaa_opens),
            *_bars("BBB", sessions, [100.0] * len(sessions)),
        ],
        backtest_config=_config(holding_sessions=20, cost_bps_per_side=10),
    )

    assert report.days[0].target_weights == {"AAA": 0.05}
    assert report.days[1].target_weights == {"AAA": 0.05, "BBB": 0.05}
    assert report.days[2].target_weights == report.days[1].target_weights
    assert report.days[2].turnover == 0
    assert report.days[2].cost == 0
    assert report.days[2].realized_max_name_weight > 0.05
    assert report.days[-1].target_weights == {"BBB": 0.05}
    _assert_portfolio_identities(report)


@pytest.mark.parametrize("holding_sessions", [1, 5, 20])
@pytest.mark.parametrize("signal_mode", ["none", "one", "many"])
def test_deterministic_scenario_grid_preserves_portfolio_invariants(
    holding_sessions,
    signal_mode,
):
    sessions = _weekdays(date(2026, 1, 5), 70)
    observed_indices = [24] if signal_mode != "many" else [24, 25, 26]
    tickers = [] if signal_mode == "none" else ["AAA", "BBB", "CCC"]
    snapshots = [
        _snapshot(
            sessions[index],
            22,
            [] if signal_mode == "none" else [_row(tickers[position])],
        )
        for position, index in enumerate(observed_indices)
    ]
    bars = [*_bars("SPY", sessions, [100 + index % 3 for index in range(70)])]
    for offset, ticker in enumerate(tickers[: len(observed_indices)]):
        bars.extend(
            _bars(
                ticker,
                sessions,
                [100 + ((index * (offset + 2)) % 7) for index in range(70)],
            )
        )
    cost_bps = {"none": 0, "one": 10, "many": 50}[signal_mode]
    config = _config(
        holding_sessions=holding_sessions,
        gross_exposure=0.6,
        max_name_weight=0.2,
        cost_bps_per_side=cost_bps,
    )

    report = run_backtest(snapshots, bars, backtest_config=config)

    for day in report.days:
        assert all(
            0 <= weight <= config.max_name_weight
            for weight in day.target_weights.values()
        )
        assert sum(day.target_weights.values()) <= config.gross_exposure + 1e-12
        assert day.realized_gross_exposure >= 0
        assert day.cash_weight >= 0
        assert day.realized_gross_exposure + day.cash_weight == pytest.approx(1)
        assert day.realized_max_name_weight <= day.realized_gross_exposure + 1e-12
    _assert_portfolio_identities(report)


def test_chronological_folds_are_ordered_and_non_overlapping():
    sessions = _weekdays(date(2026, 1, 5), 10)
    snapshots = [
        _snapshot(sessions[index], 22, [_row("AAA")]) for index in (3, 4, 5, 6)
    ]
    bars = [
        *_bars("SPY", sessions, [100 + index for index in range(len(sessions))]),
        *_bars("AAA", sessions, [100 + 2 * index for index in range(len(sessions))]),
    ]

    report = run_backtest(
        snapshots,
        bars,
        backtest_config=_config(cost_bps_per_side=0, chronological_folds=3),
    )

    assert len(report.folds) == 3
    assert all(
        previous.end <= current.start
        for previous, current in zip(report.folds, report.folds[1:])
    )


def test_backtest_cli_writes_hashed_trial_and_refuses_overwrite(tmp_path, capsys):
    sessions = _weekdays(date(2026, 1, 5), 30)
    snapshot_path = tmp_path / "snapshot.json"
    price_path = tmp_path / "prices.csv"
    output_path = tmp_path / "trial.json"
    write_snapshot(_snapshot(sessions[24], 22, [_row("AAA")]), snapshot_path)
    bars = [
        *_bars("SPY", sessions, [100 + index / 10 for index in range(len(sessions))]),
        *_bars("AAA", sessions, [100 + index / 5 for index in range(len(sessions))]),
    ]
    price_path.write_text(
        ",".join(PRICE_COLUMNS)
        + "\n"
        + "".join(
            f"{bar.date},{bar.ticker},{bar.adjusted_open},"
            f"{bar.adjusted_close},{bar.unadjusted_close},"
            f"{bar.unadjusted_volume}\n"
            for bar in bars
        ),
        encoding="utf-8",
    )

    result = backtest_main(
        [
            "--snapshots",
            str(snapshot_path),
            "--prices",
            str(price_path),
            "--output",
            str(output_path),
            "--gross-exposure",
            "1",
            "--max-name-weight",
            "1",
            "--min-average-dollar-volume",
            "0",
            "--cost-bps-per-side",
            "0",
            "--chronological-folds",
            "1",
        ]
    )

    payload = json.loads(output_path.read_text())
    assert result == 0
    assert payload["status"] == "research_only_not_implementation_ready"
    assert len(payload["trial"]["snapshot_files"][0]["sha256"]) == 64
    assert len(payload["trial"]["price_file"]["sha256"]) == 64
    assert payload["trial"]["retail_signals_version"] == __version__
    assert payload["trial"]["price_schema"] == {
        "name": PRICE_SCHEMA_NAME,
        "columns": list(PRICE_COLUMNS),
        "return_fields": ["adjusted_open", "adjusted_close"],
        "point_in_time_eligibility_fields": [
            "unadjusted_close",
            "unadjusted_volume",
        ],
    }
    assert payload["trial"]["exchange_calendar"] == {
        "name": "XNYS",
        "exchange_calendars_version": "4.13.2",
    }

    repeated = backtest_main(
        [
            "--snapshots",
            str(snapshot_path),
            "--prices",
            str(price_path),
            "--output",
            str(output_path),
        ]
    )

    assert repeated == 1
    assert "refusing to overwrite trial report" in capsys.readouterr().err


def _config(**overrides):
    values = {
        "holding_sessions": 1,
        "gross_exposure": 1.0,
        "max_name_weight": 1.0,
        "min_unadjusted_price": 0.0,
        "min_average_dollar_volume": 0.0,
        "liquidity_lookback": 2,
        "volatility_lookback": 2,
        "cost_bps_per_side": 0.0,
        "chronological_folds": 1,
    }
    values.update(overrides)
    return BacktestConfig(**values)


def _assert_portfolio_identities(report):
    assert math.prod(1 + day.net_return for day in report.days) == pytest.approx(
        report.final_nav
    )
    assert sum(day.cost for day in report.days) == pytest.approx(report.total_cost)
    assert sum(day.turnover for day in report.days) == pytest.approx(
        report.total_turnover
    )
    assert report.days[-1].nav == pytest.approx(report.final_nav)


def _snapshot(observed_date, hour, rows):
    observed_at = datetime.combine(
        observed_date,
        datetime.min.time(),
        tzinfo=UTC,
    ).replace(hour=hour)
    return capture_closed_snapshot(
        _FakeClient(rows),
        window_end=observed_date - timedelta(days=1),
        _clock=lambda: observed_at,
    )


def _row(ticker):
    return {
        "ticker": ticker,
        "buzz_score": 70.0,
        "trend": "rising",
        "mentions": 50,
        "unique_posts": 12,
        "subreddit_count": 4,
        "sentiment_score": 0.15,
        "bullish_pct": 45,
        "bearish_pct": 15,
        "total_upvotes": 500,
        "trend_history": [30.0, 40.0, 50.0],
    }


class _FakeClient:
    def __init__(self, rows):
        self.rows = rows
        self.base_url = "https://api.example.test"

    def get_trending_window(self, *, window_start, window_end, limit):
        return self.rows


def _weekdays(start, count):
    sessions = _xnys_sessions_between(start, start + timedelta(days=count * 3))
    if len(sessions) < count:
        raise AssertionError("test calendar range did not contain enough sessions")
    return sessions[:count]


def _bars(
    ticker,
    sessions,
    opens,
    *,
    volumes=None,
    adjusted_scale=1.0,
    unadjusted_closes=None,
):
    if volumes is None:
        volumes = [1_000_000] * len(sessions)
    close_offsets = [0.0, 1.0, -1.0]
    if unadjusted_closes is None:
        unadjusted_closes = [
            float(open_price + close_offsets[index % len(close_offsets)])
            for index, open_price in enumerate(opens)
        ]
    return [
        PriceBar(
            date=session,
            ticker=ticker,
            adjusted_open=float(open_price * adjusted_scale),
            adjusted_close=float(
                (open_price + close_offsets[index % len(close_offsets)])
                * adjusted_scale
            ),
            unadjusted_close=float(unadjusted_closes[index]),
            unadjusted_volume=float(volumes[index]),
        )
        for index, (session, open_price) in enumerate(zip(sessions, opens, strict=True))
    ]
