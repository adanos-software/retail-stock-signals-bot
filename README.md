# Retail Stock Signals Bot

Dry-run publisher for daily `r/RetailStockSignals` posts powered by the Adanos Reddit stock sentiment API.

Phase 1 generates a Markdown draft only. It does not post to Reddit.

## What It Does

- Fetches stock-only Reddit trending data from Adanos.
- Selects top buzz, cleanest sentiment breakout, biggest 7-day breakout, and biggest fade.
- Fetches Adanos explain context for selected tickers, but does not print raw explain text directly.
- Optionally asks DeepSeek to polish the takeaway while deterministic templates own the hook, facts, and engagement question.
- Falls back to deterministic prose when DeepSeek is unavailable.
- Uses deterministic guardrails for shared narratives, such as `GME` and `EBAY` moving on the same explanation.
- Adds contrast-first hooks, rotating SEO-safe titles, compact mobile metric lines, and data-only signal reads.
- Sanitizes generated content so unverified or messy narrative claims do not appear as facts.
- Filters numeric non-US ticker symbols from the Reddit post.
- Commits the generated `.md` draft under `public/` so Devvit can fetch it from `raw.githubusercontent.com`.
- Uploads the generated `.md` draft as a GitHub Actions artifact for review.

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

`.github/workflows/daily-publish.yml` runs at 17:55 Europe/Berlin using two
UTC cron slots plus a DST guard. The `:55` schedule avoids GitHub Actions'
high-load `:00` cron window and keeps the dated draft ready before Devvit's
publisher. It can also be run manually with `workflow_dispatch`.

The workflow generates the draft with the private Adanos and DeepSeek secrets, writes:

```text
public/daily-retail-stock-signals-YYYY-MM-DD.md
public/daily-retail-stock-signals-latest.md
```

and commits those files back to `main`. The Devvit app then reads the dated file through `raw.githubusercontent.com` and submits it to Reddit. The workflow itself does not submit anything to Reddit.

Important: Reddit Devvit can only fetch the Raw URL when the target file is publicly reachable. If this repository remains private, publish the `public/` drafts through a public mirror repository and configure the Devvit `draft_raw_base_url` setting to that mirror's Raw URL.

## AI Guardrails

DeepSeek receives structured `hard_facts` and deterministic `allowed_interpretations`. The renderer owns the title, first-line hook, facts, signal summary, final question, and disclaimer. DeepSeek output is limited to non-factual prose polish and falls back to deterministic copy when it fails guardrails.

The deterministic renderer still owns:

- ticker selection
- contrast-first intro
- SEO-safe title variation
- buzz and sentiment numbers
- 7-day mover ordering
- signal-quality interpretation
- raw explain-context exclusion from the public body
- final engagement question
- disclaimer text

If DeepSeek returns invalid JSON, times out, omits required fields, or adds blocked claim language such as hard causal/news/trading claims, the CLI logs a warning and uses deterministic fallback copy.

Explain endpoint text is treated as unverified context, not verified fact. It is not printed directly into the public Reddit body.

## Next Phases

Phase 2: review daily artifacts for several days and tune format.

Phase 3: add Reddit/PRAW submit mode with duplicate protection.
