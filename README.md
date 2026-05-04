# Retail Stock Signals Bot

Draft generator for daily `r/RetailStockSignals` posts powered by the Adanos Reddit stock sentiment API.

This repo generates and versions the Reddit draft. Posting is handled separately by the Devvit app.

## What It Does

- Fetches stock-only Reddit trending data from Adanos.
- Selects top buzz, cleanest sentiment breakout, biggest 7-day breakout, and biggest fade.
- Fetches Adanos explain context for the selected tickers.
- Optionally asks DeepSeek to polish only the intro, takeaway, and engagement question.
- Falls back to deterministic prose when DeepSeek is unavailable.
- Uses deterministic guardrails for shared narratives, such as `GME` and `EBAY` moving on the same explanation.
- Commits dated Markdown and JSON drafts for the Devvit posting app.

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
retail-stock-signals \
  --output out/daily-retail-stock-signals.md \
  --posts-dir posts \
  --drafts-dir drafts
python -m pytest
```

To disable DeepSeek even when `DEEPSEEK_API_KEY` is set:

```bash
retail-stock-signals --no-ai --output out/daily-retail-stock-signals.md
```

## Draft Files

The generator writes:

- `posts/YYYY-MM-DD.md`: human-readable Markdown archive
- `drafts/YYYY-MM-DD.json`: dated machine-readable draft
- `drafts/latest-post.json`: current draft consumed by Devvit

The JSON shape is:

```json
{
  "date": "2026-05-04",
  "subreddit": "RetailStockSignals",
  "title": "Daily Retail Stock Signals - May 4, 2026",
  "body": "### Signal Summary\n...",
  "checksum": "sha256...",
  "generated_at": "2026-05-04T20:00:00+02:00"
}
```

## Workflow

`.github/workflows/daily-dry-run.yml` runs at 20:00 Europe/Berlin using two UTC cron slots plus a DST guard. It can also be run manually with `workflow_dispatch`.

The workflow runs tests, generates the daily draft, uploads an artifact, and commits changed `drafts/` and `posts/` files back to `main`.

## AI Guardrails

DeepSeek receives the already-selected Adanos facts and explain text. It is only allowed to rewrite the intro, takeaway, and engagement question.

The deterministic renderer still owns:

- ticker selection
- buzz and sentiment numbers
- 7-day mover ordering
- explain-endpoint context
- disclaimer text

If DeepSeek returns invalid JSON, times out, or omits required fields, the CLI logs a warning and uses deterministic fallback copy.

## Next Phases

Phase 2: review daily drafts for several days and tune format.

Phase 3: let the Devvit app publish `drafts/latest-post.json` after moderator review.
