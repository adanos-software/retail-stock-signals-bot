# Retail Stock Signals Bot

Dry-run publisher for daily `r/RetailStockSignals` posts powered by the Adanos Reddit stock sentiment API.

Phase 1 generates a Markdown draft only. It does not post to Reddit.
The repository also contains an offline, research-only snapshot and paper-backtest
loop. It does not connect to a broker, place orders, or establish profitability.

## What It Does

- Fetches stock-only Reddit trending data from Adanos.
- Selects top buzz, cleanest sentiment breakout, biggest 7-day breakout, and biggest fade.
- Fetches Adanos explain context for selected tickers and prints sanitized Reddit-context lines.
- Optionally asks DeepSeek to write per-signal analysis sentences and polish the takeaway while deterministic templates own the hook, facts, and engagement question.
- Falls back to deterministic prose when DeepSeek is unavailable.
- Uses deterministic guardrails for shared narratives, such as `GME` and `EBAY` moving on the same explanation.
- Adds contrast-first hooks, rotating SEO-safe titles, compact mobile metric lines, and data-only signal reads.
- Sanitizes generated content so unverified or messy narrative claims do not appear as facts.
- Filters numeric non-US ticker symbols from the Reddit post.
- Commits the generated `.md` draft under `public/` so Devvit can fetch it from `raw.githubusercontent.com`.
- Uploads the generated `.md` draft as a GitHub Actions artifact for review.
- Captures opt-in, tamper-evident snapshots for completed Adanos UTC days.
- Runs a long-only/cash, next-session-open paper backtest with explicit costs,
  liquidity gates, position caps, chronological folds, and hashed trial inputs.

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

### Research-only workflow

Install the pinned XNYS calendar dependency with `python -m pip install -e
".[research]"` (the `dev` extra includes it as well).

Capture only a completed UTC day. The command rejects the previous day before
the 06:00 UTC finalization cutoff and refuses to overwrite an existing snapshot:

```bash
retail-stock-signals-snapshot \
  --window-end 2026-08-08 \
  --output private-research/snapshots/2026-08-08.json
```

Run one recorded paper trial against independently sourced, corporate-action-
adjusted daily bars. The CSV schema is `date,ticker,open,close,volume`; `open`
and `close` must be adjusted consistently. The report records configuration and
SHA-256 hashes for every input:

```bash
retail-stock-signals-backtest \
  --snapshots private-research/snapshots/*.json \
  --prices private-research/adjusted-prices.csv \
  --output private-research/trials/baseline-v1.json
```

The snapshot command currently captures the Adanos Reddit trending top 100, so
it is a selected-universe scaffold rather than a decision-grade point-in-time
universe. Read [the profitability research protocol](docs/PROFITABILITY_RESEARCH.md)
before interpreting any result. Live trading is explicitly out of scope.

## Workflow

The Cloudflare scheduler dispatches `.github/workflows/daily-publish.yml` at
20:00 Europe/Berlin using two UTC cron slots plus a DST guard. The workflow can
also be run manually with `workflow_dispatch`.

The workflow generates the draft with the private Adanos and DeepSeek secrets, writes:

```text
public/daily-retail-stock-signals-YYYY-MM-DD.md
public/daily-retail-stock-signals-latest.md
```

and commits those files back to `main`. The Devvit app then reads the dated file through `raw.githubusercontent.com` and submits it to Reddit. The workflow itself does not submit anything to Reddit.

Important: Reddit Devvit can only fetch the Raw URL when the target file is publicly reachable. If this repository remains private, publish the `public/` drafts through a public mirror repository and configure the Devvit `draft_raw_base_url` setting to that mirror's Raw URL.

## AI Guardrails

DeepSeek receives structured `hard_facts`, deterministic `allowed_interpretations`, and sanitized `unverified_context`. The renderer owns the title, first-line hook, metric lines, final question, and disclaimer. DeepSeek output is limited to per-signal analysis sentences and non-factual prose polish, with exact metric restatements and hype/trading phrasing stripped before rendering. It falls back to deterministic copy when it fails guardrails.

The deterministic renderer still owns:

- ticker selection
- contrast-first intro
- SEO-safe title variation
- buzz and sentiment numbers
- 7-day mover ordering
- fallback signal-quality interpretation
- sanitized explain-context framing in the public body
- final engagement question
- disclaimer text

If DeepSeek returns invalid JSON, times out, or produces no usable fields, the CLI logs a warning and uses deterministic fallback copy. Individual DeepSeek fields that fail guardrails are discarded without throwing away otherwise usable signal analysis.

Explain endpoint text is treated as unverified context, not verified fact. The public Reddit body frames it as Reddit discussion context and strips trading-call phrasing before rendering.

## Research Status

The existing published roles have no demonstrated net edge in the short archive.
Promotion requires immutable point-in-time data, a complete dated universe,
purged walk-forward evaluation, multiple-testing controls, and forward paper
trading. The explicit gates and scientific sources are documented in
[`docs/PROFITABILITY_RESEARCH.md`](docs/PROFITABILITY_RESEARCH.md).
