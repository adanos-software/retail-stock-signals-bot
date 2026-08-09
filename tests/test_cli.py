import pytest

from retail_signals import cli


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
