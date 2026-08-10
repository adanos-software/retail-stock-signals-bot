import hashlib
import json
from datetime import UTC, date, datetime

import pytest

from retail_signals.research import (
    ResearchConfig,
    ResearchSnapshot,
    capture_closed_snapshot,
    load_snapshots,
    screen_research_candidates,
    select_research_candidates,
    write_snapshot,
)
from retail_signals.snapshot_cli import main as snapshot_main


def test_capture_snapshot_uses_explicit_closed_window_and_hash(tmp_path):
    client = _FakeClient([_row("GOOD")])
    observed_at = datetime(2026, 8, 9, 6, tzinfo=UTC)

    snapshot = capture_closed_snapshot(
        client,
        window_end=date(2026, 8, 8),
        _clock=lambda: observed_at,
    )
    output = tmp_path / "snapshot.json"
    write_snapshot(snapshot, output)

    assert client.calls == [(date(2026, 8, 8), date(2026, 8, 8), 100)]
    assert snapshot.observed_at_utc == observed_at
    assert len(snapshot.content_sha256) == 64
    assert ResearchSnapshot.from_dict(json.loads(output.read_text())) == snapshot

    with pytest.raises(FileExistsError):
        write_snapshot(snapshot, output)


def test_capture_snapshot_rejects_partial_current_utc_day():
    client = _FakeClient([_row("GOOD")])

    with pytest.raises(ValueError, match="earlier than the UTC retrieval date"):
        capture_closed_snapshot(
            client,
            window_end=date(2026, 8, 9),
            _clock=lambda: datetime(2026, 8, 9, 23, tzinfo=UTC),
        )

    assert client.calls == []


def test_capture_snapshot_waits_for_closed_day_finalization():
    client = _FakeClient([_row("GOOD")])

    with pytest.raises(ValueError, match="06:00 UTC"):
        capture_closed_snapshot(
            client,
            window_end=date(2026, 8, 8),
            _clock=lambda: datetime(2026, 8, 9, 5, 59, tzinfo=UTC),
        )

    assert client.calls == []


def test_capture_snapshot_accepts_exact_finalization_cutoff():
    client = _FakeClient([_row("GOOD")])
    cutoff = datetime(2026, 8, 9, 6, tzinfo=UTC)

    snapshot = capture_closed_snapshot(
        client,
        window_end=date(2026, 8, 8),
        _clock=lambda: cutoff,
    )

    assert snapshot.observed_at_utc == cutoff
    assert client.calls == [(date(2026, 8, 8), date(2026, 8, 8), 100)]


def test_snapshot_cli_requires_environment_api_key(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ADANOS_API_KEY", raising=False)

    result = snapshot_main(["--output", str(tmp_path / "snapshot.json")])

    assert result == 2
    assert "ADANOS_API_KEY is required" in capsys.readouterr().err


@pytest.mark.parametrize("args", (("--timeout", "nan"), ("--retries", "-1")))
def test_snapshot_cli_rejects_invalid_client_options_without_traceback(
    args, monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("ADANOS_API_KEY", "test")

    with pytest.raises(SystemExit) as exc_info:
        snapshot_main(
            [
                "--output",
                str(tmp_path / "snapshot.json"),
                *args,
            ]
        )

    assert exc_info.value.code == 2
    assert "invalid" in capsys.readouterr().err


def test_snapshot_detects_content_tampering():
    snapshot = _snapshot([_row("GOOD")])
    payload = snapshot.to_dict()
    payload["rows"][0]["sentiment_score"] = 0.99

    with pytest.raises(ValueError, match="content_sha256"):
        ResearchSnapshot.from_dict(payload)

    snapshot.rows[0]["sentiment_score"] = 0.99
    with pytest.raises(ValueError, match="changed after validation"):
        snapshot.to_dict()


def test_candidate_selection_revalidates_snapshot_manifest():
    snapshot = _snapshot([_row("GOOD")])
    snapshot.rows[0]["mentions"] = 51

    with pytest.raises(ValueError, match="changed after validation"):
        select_research_candidates(snapshot, ResearchConfig())


def test_failed_snapshot_validation_does_not_create_output(tmp_path):
    snapshot = _snapshot([_row("GOOD")])
    snapshot.rows[0]["mentions"] = 51
    output = tmp_path / "snapshot.json"

    with pytest.raises(ValueError, match="changed after validation"):
        write_snapshot(snapshot, output)

    assert not output.exists()


def test_snapshot_hash_binds_decision_time_metadata():
    payload = _snapshot([_row("GOOD")]).to_dict()
    payload["observed_at_utc"] = "2026-08-09T12:00:00Z"

    with pytest.raises(ValueError, match="manifest"):
        ResearchSnapshot.from_dict(payload)


def test_snapshot_schema_rejects_multiday_windows():
    payload = _snapshot([_row("GOOD")]).to_dict()
    payload["window_start"] = "2026-08-07"
    payload["request"]["params"]["from"] = "2026-08-07"

    with pytest.raises(ValueError, match="exactly one UTC day"):
        ResearchSnapshot.from_dict(payload)


def test_capture_rejects_response_larger_than_request_limit():
    client = _FakeClient([_row("GOOD"), _row("EXTRA")])

    with pytest.raises(ValueError, match="row count exceeds"):
        capture_closed_snapshot(
            client,
            window_end=date(2026, 8, 8),
            limit=1,
            _clock=lambda: datetime(2026, 8, 9, 6, tzinfo=UTC),
        )


def test_snapshot_load_rejects_rehashed_rows_above_request_limit(tmp_path):
    payload = _snapshot([_row("GOOD")], limit=1).to_dict()
    payload["rows"].append(_row("EXTRA"))
    _rehash_payload(payload)
    path = tmp_path / "oversized.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="row count exceeds"):
        load_snapshots([path])


def test_capture_rejects_duplicate_normalized_tickers():
    with pytest.raises(ValueError, match="duplicate ticker GOOD"):
        _snapshot([_row("GOOD"), _row(" good ")], limit=2)


def test_snapshot_load_rejects_rehashed_duplicate_ticker(tmp_path):
    payload = _snapshot([_row("GOOD")], limit=2).to_dict()
    payload["rows"].append(_row("good"))
    _rehash_payload(payload)
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate ticker GOOD"):
        load_snapshots([path])


@pytest.mark.parametrize(
    "base_url",
    (
        "https://user:dummy@api.example.test",
        "https://api.example.test?token=dummy",
        "https://api.example.test:invalid",
    ),
)
def test_snapshot_load_rejects_credential_bearing_or_invalid_base_url(
    base_url, tmp_path
):
    payload = _snapshot([_row("GOOD")]).to_dict()
    payload["request"]["base_url"] = base_url
    _rehash_payload(payload)
    path = tmp_path / "invalid-base-url.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="base_url is invalid"):
        load_snapshots([path])


@pytest.mark.parametrize(
    "ticker", (None, 123, "BAD TICKER", "BAD.", "BAD..CLASS", "-BAD")
)
def test_capture_rejects_invalid_research_ticker(ticker):
    with pytest.raises(ValueError, match="invalid research ticker"):
        _snapshot([_row(ticker)])


def test_capture_records_response_completion_time():
    request_started = datetime(2026, 8, 9, 13, 29, 59, tzinfo=UTC)
    response_completed = datetime(2026, 8, 9, 13, 30, 1, tzinfo=UTC)

    times = iter((request_started, response_completed))

    snapshot = capture_closed_snapshot(
        _FakeClient([_row("GOOD")]),
        window_end=date(2026, 8, 8),
        _clock=lambda: next(times),
    )

    assert snapshot.observed_at_utc == response_completed


def test_long_only_research_config_requires_positive_direction():
    with pytest.raises(ValueError, match="min_sentiment"):
        ResearchConfig(min_sentiment=0)
    with pytest.raises(ValueError, match="min_bull_bear_spread"):
        ResearchConfig(min_bull_bear_spread=0)


def test_research_signal_separates_direction_quality_and_crowding():
    good = _row("GOOD")
    gap_history_variant = _row("GAP", trend_history=[0.0, 0.0, 80.0])
    crowded = _row("CROWD", buzz_score=90.0)
    attention_only = _row("LOUD", sentiment_score=-0.1, bullish_pct=15, bearish_pct=45)
    thin = _row("THIN", mentions=3, unique_posts=1, subreddit_count=1)
    falling = _row("FALL", trend="falling")

    candidates = select_research_candidates(
        _snapshot([good, gap_history_variant, crowded, attention_only, thin, falling]),
        ResearchConfig(),
    )

    assert {candidate.ticker for candidate in candidates} == {"GOOD", "GAP"}
    assert candidates[0].score == candidates[1].score


def test_social_screen_reports_deterministic_rejection_reasons():
    rows = [
        _row("GOOD"),
        _row("FALL", trend="falling"),
        _row("THIN", mentions=3, unique_posts=1, subreddit_count=1),
        _row("CROWD", buzz_score=90.0),
    ]

    candidates, rejections = screen_research_candidates(
        _snapshot(rows), ResearchConfig()
    )

    assert [candidate.ticker for candidate in candidates] == ["GOOD"]
    assert rejections == [
        ("FALL", "social_screen_trend_not_rising"),
        ("THIN", "social_screen_min_mentions"),
        ("CROWD", "social_screen_max_crowding_buzz"),
    ]


def test_research_signal_fails_closed_on_missing_quality_fields():
    incomplete = _row("NOPE")
    incomplete.pop("unique_posts")

    assert select_research_candidates(_snapshot([incomplete]), ResearchConfig()) == []


def test_research_signal_rejects_inconsistent_sentiment_percentages():
    inconsistent = _row("NOPE", bullish_pct=90, bearish_pct=20)

    assert select_research_candidates(_snapshot([inconsistent]), ResearchConfig()) == []


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("mentions", True),
        ("unique_posts", 12.0),
        ("subreddit_count", "4"),
        ("bullish_pct", True),
        ("bearish_pct", 15.0),
    ),
)
def test_research_signal_requires_strict_integer_activity_fields(field, value):
    malformed = _row("NOPE", **{field: value})

    assert select_research_candidates(_snapshot([malformed]), ResearchConfig()) == []


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("buzz_score", True),
        ("buzz_score", "70"),
        ("sentiment_score", True),
        ("sentiment_score", "0.15"),
    ),
)
def test_research_signal_requires_strict_numeric_score_fields(field, value):
    malformed = _row("NOPE", **{field: value})

    assert select_research_candidates(_snapshot([malformed]), ResearchConfig()) == []


@pytest.mark.parametrize(
    "overrides",
    (
        {"mentions": 20, "unique_posts": 21},
        {"unique_posts": 5, "subreddit_count": 6},
    ),
)
def test_research_signal_rejects_inconsistent_breadth(overrides):
    inconsistent = _row("NOPE", **overrides)

    assert select_research_candidates(_snapshot([inconsistent]), ResearchConfig()) == []


def test_research_signal_fails_closed_on_log_overflow():
    huge = 10**400
    oversized = _row(
        "NOPE",
        mentions=huge,
        unique_posts=huge,
        subreddit_count=huge,
    )

    assert select_research_candidates(_snapshot([oversized]), ResearchConfig()) == []


class _FakeClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
        self.base_url = "https://api.example.test"

    def get_trending_window(self, *, window_start, window_end, limit):
        self.calls.append((window_start, window_end, limit))
        return self.rows


def _snapshot(rows, *, limit=100):
    return capture_closed_snapshot(
        _FakeClient(rows),
        window_end=date(2026, 8, 8),
        limit=limit,
        _clock=lambda: datetime(2026, 8, 9, 6, tzinfo=UTC),
    )


def _rehash_payload(payload):
    manifest = {key: value for key, value in payload.items() if key != "content_sha256"}
    canonical = json.dumps(
        manifest,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["content_sha256"] = hashlib.sha256(canonical).hexdigest()


def _row(ticker, **overrides):
    row = {
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
        "trend_history": [35.0, 45.0, 55.0],
    }
    row.update(overrides)
    return row
