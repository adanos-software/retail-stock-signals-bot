from retail_signals import cli


def test_cli_requires_adanos_api_key(monkeypatch, capsys):
    monkeypatch.delenv("ADANOS_API_KEY", raising=False)

    result = cli.main(["--no-ai"])

    captured = capsys.readouterr()
    assert result == 2
    assert "ADANOS_API_KEY is required" in captured.err


def test_cli_falls_back_when_deepseek_fails(monkeypatch, tmp_path, capsys):
    output_path = tmp_path / "draft.md"
    posts_dir = tmp_path / "posts"
    drafts_dir = tmp_path / "drafts"
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
            "--date",
            "2026-05-04",
            "--output",
            str(output_path),
            "--posts-dir",
            str(posts_dir),
            "--drafts-dir",
            str(drafts_dir),
        ]
    )

    assert result == 0
    captured = capsys.readouterr()
    assert "DeepSeek disabled for this run: unit failure" in captured.err
    draft = output_path.read_text(encoding="utf-8")
    assert "Title: Daily Retail Stock Signals - May 4, 2026" in draft
    assert "Today's signal:" in draft
    assert "GME is trending because of a shared eBay narrative." in draft

    archived_post = posts_dir / "2026-05-04.md"
    latest_draft = drafts_dir / "latest-post.json"
    dated_draft = drafts_dir / "2026-05-04.json"
    assert archived_post.read_text(encoding="utf-8") == draft
    assert latest_draft.read_text(encoding="utf-8") == dated_draft.read_text(encoding="utf-8")
    assert '"date": "2026-05-04"' in latest_draft.read_text(encoding="utf-8")
    assert '"subreddit": "RetailStockSignals"' in latest_draft.read_text(encoding="utf-8")


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
            return "GME is trending because of a shared eBay narrative."
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
