# Retail Stock Signals Bot

Dry-run publisher for daily `r/RetailStockSignals` posts powered by the Adanos Reddit stock sentiment API.

Phase 1 generates a Markdown draft only. It does not post to Reddit.

## What It Does

- Fetches stock-only Reddit trending data from Adanos.
- Selects top buzz, cleanest sentiment breakout, biggest 7-day breakout, and biggest fade.
- Fetches Adanos explain context for the selected tickers.
- Optionally asks DeepSeek to polish only the intro, takeaway, and engagement question.
- Falls back to deterministic prose when DeepSeek is unavailable.
- Uploads the generated `.md` draft as a GitHub Actions artifact.

## GitHub Secrets

Required:

```text
ADANOS_API_KEY
```

Optional:

```text
DEEPSEEK_API_KEY
```

## Local Usage

```bash
python -m pip install -e ".[dev]"
retail-stock-signals --output out/daily-retail-stock-signals.md
python -m pytest
```

To disable DeepSeek even when `DEEPSEEK_API_KEY` is set:

```bash
retail-stock-signals --no-ai --output out/daily-retail-stock-signals.md
```

## Workflow

`.github/workflows/daily-dry-run.yml` runs at 09:00 Europe/Berlin using two UTC cron slots plus a DST guard. It can also be run manually with `workflow_dispatch`.

## Next Phases

Phase 2: review daily artifacts for several days and tune format.

Phase 3: add Reddit/PRAW submit mode with duplicate protection.
