from http.client import IncompleteRead

import pytest

from retail_signals import cli, snapshot_cli
from retail_signals.adanos import AdanosApiError


def test_cli_requires_adanos_api_key(monkeypatch, capsys):
    monkeypatch.delenv("ADANOS_API_KEY", raising=False)

    result = cli.main(["--no-ai"])

    captured = capsys.readouterr()
    assert result == 2
    assert "ADANOS_API_KEY is required" in captured.err


@pytest.mark.parametrize("args", (("--timeout", "nan"), ("--retries", "-1")))
def test_cli_rejects_invalid_client_options_without_traceback(args, capsys):
    with pytest.raises(SystemExit) as exc_info:
        cli.main([*args, "--api-key", "test"])

    assert exc_info.value.code == 2
    assert "invalid" in capsys.readouterr().err


def test_cli_falls_back_when_deepseek_fails(monkeypatch, tmp_path, capsys):
    output_path = tmp_path / "draft.md"
    fake_client = _FakeAdanosClient(
        api_key="test",
        base_url="https://api.example.test",
        timeout=30.0,
        retries=2,
    )

    monkeypatch.setattr(cli, "AdanosClient", lambda **kwargs: fake_client)
    monkeypatch.setattr(cli.DeepSeekClient, "generate_copy", _raise_deepseek)

    result = cli.main(
        [
            "--api-key",
            "test",
            "--deepseek-api-key",
            "bad-key",
            "--date-label",
            "May 4, 2026",
            "--output",
            str(output_path),
        ]
    )

    assert result == 0
    captured = capsys.readouterr()
    assert "DeepSeek disabled for this run: unit failure" in captured.err
    draft = output_path.read_text(encoding="utf-8")
    assert "Title: Daily Retail Stock Signals - May 4, 2026" in draft
    assert "Today's split:" in draft
    assert "Reddit discussion appears tied to:" not in draft


@pytest.mark.parametrize(
    "args",
    (
        ("--timezone", "Mars/Olympus"),
        ("--limit", "0"),
        ("--limit", "101"),
        ("--adanos-base-url", "not-a-url"),
    ),
)
def test_cli_rejects_invalid_runtime_options_without_traceback(args, capsys):
    with pytest.raises(SystemExit) as exc_info:
        cli.main([*args, "--api-key", "test"])

    assert exc_info.value.code == 2
    assert "Traceback" not in capsys.readouterr().err


def test_cli_does_not_echo_credentials_from_a_rejected_base_url(capsys):
    sentinel = "dummy"

    with pytest.raises(SystemExit) as exc_info:
        cli.main(
            [
                "--adanos-base-url",
                f"https://user:{sentinel}@api.example.test",
                "--api-key",
                "test",
            ]
        )

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert sentinel not in captured.err
    assert "must not contain credentials" in captured.err


def test_cli_reports_adanos_failure_without_traceback_or_secret(monkeypatch, capsys):
    sentinel = "dummy"

    monkeypatch.setattr(
        "retail_signals.adanos.request.urlopen",
        lambda api_request, timeout: _TruncatedResponse(),  # noqa: ARG005
    )

    result = cli.main(["--api-key", sentinel, "--no-ai", "--retries", "0"])

    assert result == 1
    captured = capsys.readouterr()
    assert "Adanos fetch failed" in captured.err
    assert "Traceback" not in captured.err
    assert sentinel not in captured.err


def test_snapshot_cli_reports_truncated_response_without_traceback(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("ADANOS_API_KEY", "test")
    monkeypatch.setattr(
        "retail_signals.adanos.request.urlopen",
        lambda api_request, timeout: _TruncatedResponse(),  # noqa: ARG005
    )

    result = snapshot_cli.main(
        [
            "--output",
            str(tmp_path / "snapshot.json"),
            "--window-end",
            "2026-08-08",
            "--retries",
            "0",
        ]
    )

    assert result == 1
    captured = capsys.readouterr()
    assert "Adanos fetch failed" in captured.err
    assert "Traceback" not in captured.err


def test_cli_continues_when_optional_explanation_fails(monkeypatch, tmp_path, capsys):
    output_path = tmp_path / "draft.md"
    fake_client = _FakeAdanosClient()

    def fail_explanation(ticker):  # noqa: ARG001
        raise AdanosApiError("explain unavailable")

    fake_client.get_explanation = fail_explanation
    monkeypatch.setattr(cli, "AdanosClient", lambda **kwargs: fake_client)

    result = cli.main(
        [
            "--api-key",
            "test",
            "--no-ai",
            "--date-label",
            "May 4, 2026",
            "--output",
            str(output_path),
        ]
    )

    assert result == 0
    assert output_path.exists()
    captured = capsys.readouterr()
    assert "explanation unavailable" in captured.err


def test_cli_reports_output_failure_without_traceback(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "AdanosClient", _FakeAdanosClient)

    result = cli.main(
        [
            "--api-key",
            "test",
            "--no-ai",
            "--date-label",
            "May 4, 2026",
            "--output",
            str(tmp_path),
        ]
    )

    assert result == 1
    captured = capsys.readouterr()
    assert "ERROR:" in captured.err
    assert "Traceback" not in captured.err


class _FakeAdanosClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def get_trending(self, *, days, limit):
        del limit
        if days == 1:
            return [
                _row("GME", 82.0, 0.0, 28, 28, [80, 82]),
                _row("XRX", 72.0, 0.18, 51, 13, [20, 72]),
                _row("POET", 62.0, -0.05, 25, 36, [71, 62], trend="falling"),
            ]
        return [
            _row("GME", 82.0, 0.0, 28, 28, [80, 82]),
            _row("XRX", 72.0, 0.18, 51, 13, [20, 72]),
            _row("POET", 62.0, -0.05, 25, 36, [71, 62], trend="falling"),
        ]

    def get_explanation(self, ticker):
        if ticker == "GME":
            return "GME is trending because a shared eBay narrative is being discussed."
        return ""


def _raise_deepseek(self, signals):
    del self, signals
    raise cli.DeepSeekError("unit failure")


class _TruncatedResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        raise IncompleteRead(b"[", 1)


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
