# Profitability research protocol

> **Status: research only — no demonstrated profit, no live-trading approval.**
> This repository is a Markdown publisher, not a trading bot. Nothing in this
> document or the accompanying pull request places orders, connects a broker,
> recommends a security, or establishes that any strategy is profitable.

## Executive finding

The scheduled application on the audited `origin/main` baseline fetches Adanos
Reddit trending data, selects four editorial roles, optionally asks DeepSeek for
guarded prose, and writes a daily Reddit draft. That baseline has no
point-in-time research store, price feed, order model, portfolio accounting,
risk engine, execution adapter, or backtester. Any offline research harness
added alongside this document does not change the scheduled publisher into a
trading bot or retroactively create point-in-time data.

A retrospective diagnostic of the 86 dated Markdown snapshots finds no stable
profitability in the published roles. At a fixed 20 bp round-trip cost, the
published `Top Buzz` role was negative on average at one-, three-, and
five-session horizons. `Largest 7-Day Buzz Move` was positive for one session
but negative at three and five sessions. The sample is short, dependent, and
not point-in-time complete; these numbers are a warning against promoting the
publisher's labels into orders, not evidence for a profitable replacement.

The pull request therefore adds only a conservative, screen-grade research
scaffold: a closed-day Reddit snapshot, one preregistered long-only/cash rule,
and an open-to-open paper simulator. It is a feedback loop for collecting and
falsifying evidence, not a scientifically validated strategy. Decision-grade
research still requires the immutable metadata, complete universe, purged
walk-forward validation, and realistic cost work specified below. Live trading
remains explicitly out of scope.

## 1. Current-system audit

### What the scheduled publisher actually does

1. `retail_signals.cli` requests `/reddit/stocks/v1/trending` for `days=1` and
   `days=7`.
2. `retail_signals.signals` converts the returned rows into editorial roles:
   `Top Buzz`, `Best Sentiment Read`, `Largest 7-Day Buzz Move`, and
   `7-Day Buzz Fade`.
3. Adanos `/explain` text and optional DeepSeek output affect public prose, not
   an executable portfolio.
4. `retail_signals.render` produces Markdown; the scheduled workflow commits
   the dated and `latest` drafts for a separate publisher.

There is no broker dependency or order path. The existing workflow also runs
before the US cash close, while the API's days-only history can include an
unfinished current UTC day. That is acceptable for an attention post but not
for a causal end-of-day trading study.

### Why the displayed labels are not alpha factors

- `buzz_score` is a bounded, nonlinear attention score and already incorporates
  sentiment. Combining buzz, `sentiment_score`, and bullish/bearish shares as if
  they were independent factors double-counts related information.
- The existing seven-day change subtracts the first and last values of
  `trend_history`. The final value can be partial, and a missing day can appear
  as `0.0`; neither is valid evidence of acceleration.
- `/trending?limit=50` defines a selected top-buzz set, not a point-in-time
  investable universe. The lowest change within that set is not necessarily the
  market's largest fade.
- Historical rows are resolved through current reference data. Without a
  dated universe containing delisted and renamed securities, survivorship and
  symbol-mapping bias remain possible.
- AI explanations have a moving model/prompt and no historical `as_of`
  contract. They must never enter numerical research features.
- The archived Markdown omits the full response, absent candidates, retrieval
  time, API version, pagination, and content hash. It cannot reconstruct what
  was knowable at the decision time.

The accompanying publisher fixes make a missing explanation nonfatal and only
assign breakout/fade roles when their delta has the claimed sign. The new
offline modules add tamper-evident Reddit snapshots and a paper simulation, but
do not alter the publishing workflow or place orders. Both are research and
correctness scaffolding, not a profitability optimization.

## 2. Diagnose feedback loop and observed baseline

The immediate feedback loop parses each dated archive, maps a published signal
to the next exchange session, deduplicates by `(role, ticker, entry_date)`, and
measures one-, three-, and five-session returns under one fixed execution/cost
convention. It reproduced the relevant symptom: the current editorial choices
do not exhibit a stable net edge.

### Diagnostic convention

- Source: 86 rendered snapshots currently in `public/`; they are files, not 86
  independent trading sessions.
- Entry convention: next actual US exchange session open.
- Cost: 20 bp round trip, deducted from every event return.
- Duplicate key: published role, ticker, and entry date.
- Prices: Yahoo OHLC used solely for this diagnostic; four of 103 parsed symbols
  had no usable Yahoo history.
- The independent unit is not a row in the tables. Signals share dates and
  tickers, and multi-session holdings overlap; naive event-level t-statistics
  would be invalid and are intentionally not reported.

### Net mean return by published role

| Published role | 1 session | 3 sessions | 5 sessions |
|---|---:|---:|---:|
| Top Buzz | n=62, **-0.934%** | n=60, **-2.430%** | n=57, **-4.167%** |
| Best Sentiment Read | n=61, **+0.176%** | n=59, **-0.471%** | n=56, **-2.296%** |
| Largest 7-Day Buzz Move | n=71, **+0.306%** | n=69, **-1.785%** | n=65, **-4.303%** |
| 7-Day Buzz Fade, held long | n=81, **-0.436%** | n=79, **-0.396%** | n=75, **+0.040%** |

### One-session diagnostics

| Published role | Median net return | Positive-return rate | Mean SPY-excess return |
|---|---:|---:|---:|
| Top Buzz | -1.017% | 37.1% | -1.028% |
| Best Sentiment Read | -0.139% | 45.9% | +0.133% |
| Largest 7-Day Buzz Move | +0.221% | 52.1% | +0.221% |
| 7-Day Buzz Fade, held long | -0.357% | 48.1% | -0.456% |

The positive one-session breakout mean is not a finding of alpha. It reverses
in this small sample at longer horizons, was examined alongside multiple roles
and horizons, and lacks valid uncertainty estimates. Likewise, the slightly
positive five-session fade result is economically close to zero before any
more realistic liquidity-dependent cost model.

### Methodological limits of this baseline

1. The 86 files cover a short, single market regime and include weekends and
   repeated signals; effective sample size is much smaller than the row counts.
2. Published roles may have been produced by changing code and prose logic.
   The archive contains selected winners, not the candidate population.
3. No API key or previously persisted point-in-time Adanos responses were
   available for this audit. A historical API query made now could include
   late-arriving data and would not prove what was visible then.
4. Yahoo data are a convenient diagnostic source, not a locked institutional
   execution dataset. Missing/delisted symbols, corporate actions, opening
   auctions, halts, spread, impact, and rejected fills are not fully modeled.
5. A constant 20 bp cost ignores the strong relation between liquidity and
   effective trading cost documented by [Hasbrouck (2009)](https://doi.org/10.1111/j.1540-6261.2009.01469.x).
6. Overlapping labels, serial dependence, cross-sectional dependence, repeated
   tickers, and strategy selection invalidate ordinary iid tests.
7. The result is retrospective and selected after seeing the archive. It is not
   an untouched out-of-sample test.

## 3. Scientific basis and falsifiable hypotheses

The literature does not justify a generic "more retail buzz means buy" rule.
[Antweiler and Frank (2004)](https://doi.org/10.1111/j.1540-6261.2004.00662.x)
found message-board information useful for volatility while its return effect
was economically small, and
[Kim and Kim (2014)](https://doi.org/10.1016/j.jebo.2014.04.015) found no
future-return predictability from their message sentiment sample. Attention is
also not direction: [Barber and Odean (2008)](https://doi.org/10.1093/rfs/hhm079)
show that attention-grabbing securities attract individual-investor buying;
[Da, Engelberg, and Gao (2011)](https://doi.org/10.1111/j.1540-6261.2011.01679.x)
document short-run price pressure followed by reversal; and
[Barber et al. (2022)](https://doi.org/10.1111/jofi.13183) find intense
attention-induced Robinhood buying forecasts negative abnormal returns. These
results motivate separating direction, attention, evidence quality, and
crowding instead of treating one composite buzz score as a trade.

The hypotheses below are ranked and falsifiable. The null throughout is that
net excess return is nonpositive.

1. **H1 — qualified direction (implemented v1 screen).** Within the biased
   Reddit top-100 set, positive direction predicts positive subsequent
   open-to-open return only when it has minimum activity/breadth and is not in
   the most crowded buzz tail. Prediction: the frozen v1 screen has positive
   net return and beats exposure-matched SPY/cash plus direction-only and
   attention-only ablations out of sample. The current archive cannot test this
   prediction validly.
2. **H2 — attention crowding.** Extreme attention is primarily a crowding/risk
   state, not bullish direction. Prediction: after conditioning on direction
   and prior returns, the highest attention tail performs no better than the
   moderate-attention group and may underperform it.
3. **H3 — independent confirmation (future).** Agreement across independently measured
   Reddit, X, and news direction/quality is more reliable than repeated fields
   derived from one platform's buzz formula. Prediction: cross-platform
   confirmation improves out-of-sample calibration and net excess return;
   replacing it with extra buzz-derived terms does not.
4. **H4 — no durable edge.** Any apparent historical gain is leakage, selection,
   or cost sensitivity. Prediction: the edge disappears under immutable
   snapshots, purged walk-forward evaluation, complete trial accounting, and
   50 bp cost stress. This is the default conclusion unless rejected by the
   gates below.

## 4. Implemented v1: preregistered screen-grade hypothesis

This is the exact conservative rule implemented by the pull request. It is a
research scaffold, not a recommended allocation or the complete scientific
strategy described by H1-H4.

### Selected universe and known bias

V1 captures at most 100 rows from one closed-day Reddit `/trending` response and
labels the universe `adanos-reddit-trending-top-100`. This is a top-attention
screen, not a point-in-time US equity universe. It excludes securities that did
not rank, can depend on today's symbol/reference state, and cannot represent
delisted names absent from the response. V1 results must therefore be labeled
`selected-universe` and cannot support a market-wide profitability claim.

At the simulated decision time, v1 additionally requires an adjusted prior
close of at least $5, trailing 20-session average dollar volume of at least
$10 million, and exact coverage of the required preceding benchmark sessions
for a 20-session realized-volatility estimate. A missing recent ticker bar is a
failed eligibility input; older observations are never compressed across the
gap.

### Coarse D/A/Q/C operationalization

V1 separates the concepts enough to make one falsifiable screen, but its inputs
remain correlated and must not be presented as independent factors.

| Pillar | V1 implementation | Limitation / decision-grade successor |
|---|---|---|
| `D` direction | `sentiment_score >= 0.05` and bullish minus bearish share at least 10 percentage points | Both fields come from one Reddit classifier; later test calibrated direction separately by platform |
| `A` attention | API `trend == rising` and at least 20 mentions | `trend` is not a point-in-time abnormal-mention measure and buzz embeds sentiment; later use closed-day `log1p(mentions)` surprise versus trailing history |
| `Q` quality | At least 5 unique posts and 3 subreddits; score multiplies `log1p(unique_posts) * log1p(subreddit_count)` | Breadth is Reddit-only; later require author/source concentration checks and independent X/news confirmation |
| `C` crowding/risk | Exclude `buzz_score >= 85`; price/liquidity/volatility screens in the simulator | A fixed buzz cutoff is only a coarse crowding proxy; later model extreme attention, gaps, idiosyncratic return, volatility, impact, and concentration separately |

For rows passing all screens, v1 ranks
`sentiment_score * (bull_bear_spread / 100) * log1p(unique_posts) * log1p(subreddit_count)`
across the full social-screened page, applies price/liquidity/volatility
eligibility in that order, and only then keeps the first five eligible names.
`/explain` and all LLM text are excluded from this numeric path.

### Implemented portfolio defaults

1. Timestamp the snapshot only after the Adanos response has completed, then
   map it to the first benchmark/US session open strictly after that UTC
   observation timestamp. Reject multiple vintages for the same signal day.
2. Within a signal cohort, divide the score by trailing 20-session annualized
   volatility and allocate proportionally. The cohort budget is 25% gross
   divided by the configured holding horizon; each name is capped at 5%.
   Targets are sized against post-cost NAV, so transaction fees are reserved
   without borrowing and configured gross/name caps remain true after costs.
3. Combine active cohorts, keep gross exposure at or below 25%, and leave the
   remainder in non-interest-bearing simulated cash. There is no leverage,
   shorting, sector constraint, or portfolio volatility target in v1.
4. The CLI exposes fixed holding variants of 1, 5, or 20 sessions. One session
   is the default. These are separate registered trials; v1 does not implement
   the archive diagnostic's 3-session variant. A cohort is included only when
   the price input contains its full configured horizon; right-censored
   holdings are never shortened or scored.
5. Charge 10 bp per traded side by default (20 bp for a fully entered and later
   liquidated position). Missing eligibility inputs leave the name out; no
   qualified cohort means cash.

Every change to a screen, score, budget, cap, cost, or horizon creates a new
trial. V1 must first accumulate new immutable snapshots; running it on data
queried retrospectively would not convert that data into point-in-time evidence.

### Decision-grade successor, not implemented

The full research candidate must use a dated US common-stock universe including
delistings and symbol history, full/batched coverage rather than `/trending`,
and separately standardized Reddit/X direction, raw attention surprise,
evidence quality, news confirmation, and crowding. Polymarket may be tested only
as a separately standardized event-risk feature because its flow semantics
differ. Learned coefficients, sector constraints, a portfolio volatility target,
and point-in-time short interest are future trials, not v1 behavior.

## 5. Adanos closed-day snapshot contracts

### Implemented v1 contract

V1 captures exactly one Reddit page for closed UTC day `D`:

```text
GET /reddit/stocks/v1/trending?from=D&to=D&type=stock&limit=100&offset=0
```

Capture is rejected before the closed-day rollup is ready: `D` must be earlier
than the retrieval date and retrieval must not occur before 06:00 UTC on `D+1`.
The `adanos.reddit-stocks.research-snapshot.v1` file contains the response-
completion UTC observation timestamp, one-day window start/end, canonical
request path/query metadata, explicit top-100 universe label, canonicalized JSON
rows, schema name, and SHA-256 of that complete canonical manifest. Loading
revalidates the hash, one-day window, and closed-window request; writing uses an
exclusive create and refuses to replace an existing file. The research client
rejects the entire response if any API list element is not an object; it never
silently deletes malformed rows before hashing.

This makes accidental mutation detectable and enforces a basic closed-day
cutoff. It does **not** preserve the raw HTTP response, request/response headers,
ETag, API version, quota state, ingestion commit, pagination chain, security
master vintage, or a previous-manifest hash. It also does not collect beyond
the first 100 ranked Reddit rows or any other platform. V1 is therefore a
screen-grade evidence object, not the final decision-grade provenance contract.

The shared HTTP client treats an explanation `404` as absent context, stops on
a quota `429` without `Retry-After`, and retries a burst `429` using either
delta-seconds or an HTTP date. A server-controlled delay is capped at 60 seconds
per retry so a response cannot indefinitely stall the publisher or collector.

### Required decision-grade future contract

For every platform, fetch only after its closed-day rollup is finalized and
before any next-session order. Use exact inclusive dates, never a rolling
`days` query, and collect every page or a fixed batched universe:

```text
GET /reddit/stocks/v1/trending?from=D&to=D&type=stock&limit=100&offset=...
GET /x/stocks/v1/trending?from=D&to=D&type=stock&limit=100&offset=...
GET /news/stocks/v1/trending?from=D&to=D&type=stock&limit=100&offset=...
GET /polymarket/stocks/v1/trending?from=D&to=D&type=stock&limit=100&offset=...
```

Store the first valid raw response bytes append-only. The future manifest must
add:

- canonical request URL/query and ordered pagination;
- `retrieved_at_utc`, signal date, intended first order timestamp, timezone,
  and exchange calendar version;
- HTTP status plus `Date`, `ETag`, API/root version, quota metadata, and response
  schema version when present;
- raw response SHA-256, row count, ticker-set hash, and previous-manifest hash;
- repository commit, feature-config hash, universe-vintage hash, and ingestion
  code version; and
- explicit missing/null fields, retry history, and any late/corrected replacement.

Never overwrite a snapshot. A later refetch is a new vintage and cannot replace
the first eligible decision-time observation in a backtest. Enforce
`feature_cutoff < order_timestamp` in code and reject current/incomplete dates.
Closed-day reconstruction, zero-padded history, an ETag, or a later historical
API response must not be mistaken for decision-time evidence.

Use strict platform schemas. Preserve raw activity and breadth fields such as
Reddit mentions/unique posts/subreddit count, X mentions/unique tweets, news
mentions/source count, and period-scoped Polymarket trade/market/liquidity
fields. Never use Polymarket `current_market_count`, `pulse`, or today's
`active`/`market_status` as historical features.

## 6. Portfolio simulation and validation

### Implemented v1 simulation

V1 loads a strict adjusted daily `date,ticker,open,close,volume` CSV and validates
every supplied SPY session against the pinned
[`exchange-calendars` 4.13.2](https://pypi.org/project/exchange-calendars/4.13.2/)
XNYS calendar. A missing or unexpected benchmark session fails the trial; snapshots
cannot silently advance to a later available row. V1 enters only at the first
actual XNYS open after response completion. It rejects duplicate vintages for
one signal day and excludes any cohort without the full requested holding
horizon. It marks active cohorts open-to-open, charges turnover at 10 bp per
side, charges final liquidation in both daily and aggregate metrics, and assigns
every sell fee to the return period ending at that exit open while a buy fee
starts the new period. It holds idle cash at zero return and fails on a missing
held-ticker bar rather than inventing a fill.

The JSON report refuses overwrite and records snapshot/price file hashes, the
full research and backtest configs, created time, benchmark, XNYS calendar
library/version, daily weights, turnover, costs, NAV, and SPY return. It reports
total/annualized return,
annualized volatility, a deliberately named **naive** Sharpe, maximum drawdown,
hit rate, and contiguous descriptive folds. These folds do not train, purge,
embargo, or establish out-of-sample validity. The reported SPY series is
full-notional rather than matched to v1's 25% gross budget, so it is descriptive,
not by itself a fair superiority test.

### Decision-grade simulation requirements

- Replace user-supplied adjusted CSV assumptions with a vetted point-in-time
  security master, corporate actions, delistings, and executable auction/quote
  data with a consistent total-return ledger. Archive and audit the exact
  exchange-calendar vintage and exceptional closures used by each trial.
- Never fill before the signal or silently advance to a favorable print. Model
  halts, rejected/partial orders, dividends, cash yield, and realized exposure.
- Keep the v1 20 bp round-trip baseline but require 10/50 bp sensitivity. With
  quote/trade data, separately charge half-spread, fees, slippage, and nonlinear
  impact. Add a preregistered participation cap and report capacity.
- Report net CAGR/mean return, Sharpe and Sortino ratios, SPY- and sector-excess
  return, beta/factor alpha, volatility, maximum drawdown, expected shortfall,
  hit rate, turnover, gross/net exposure, concentration, rejected fills, and
  liquidity/capacity by regime. Show uncertainty and the full distribution.
- Model the portfolio as one path; never treat overlapping event rows as
  independent trades.

### Required walk-forward design — not implemented in v1

Use chronological expanding or rolling origins as described in
[Tashman (2000)](https://doi.org/10.1016/S0169-2070(00)00065-0), never random
train/test splits. Before research begins, freeze calendar boundaries, minimum
training length, retraining cadence, and untouched final holdout. Purge training
labels whose holding interval overlaps validation/test and embargo at least the
maximum holding horizon. Fit transforms, thresholds, universe filters, and any
model only on the training window.

Do not tune on the current 86-snapshot archive. Begin model selection only after
at least 252 complete exchange sessions of immutable data. Report every fold and
regime; concatenate only genuinely out-of-sample portfolio returns. Use a
stationary/block bootstrap or HAC inference appropriate to serial and
cross-sectional dependence.

### Required benchmarks and ablations — not implemented in v1

Every fold must compare the same dates, universe, costs, and risk budget against:

1. cash and SPY buy-and-hold;
2. equal-weight eligible universe and sector-matched random portfolios;
3. simple 12-1 price momentum and short-horizon reversal controls;
4. current `Top Buzz`, `Best Sentiment`, `Buzz Breakout`, and `Buzz Fade` rules;
5. v1 qualified-direction screen, `D` only, `A` only, `D+A`, `D+A+Q`, and a
   future fully separated `D+A+Q-C` model;
6. Reddit only versus Reddit+X, then independent news and Polymarket additions;
7. gross, 10 bp, 20 bp, and 50 bp cost cases plus liquidity buckets.

An addition is useful only if its incremental out-of-sample result is stable,
net of cost, and not concentrated in one ticker, date, sector, or regime.

### Required multiple-testing controls and trial ledger — not implemented in v1

Data reuse can make the best searched model look predictive by chance; see
[White (2000)](https://doi.org/10.1111/1468-0262.00152) and
[Harvey, Liu, and Zhu (2016)](https://doi.org/10.1093/rfs/hhv059). Maintain an
append-only trial ledger containing the hypothesis timestamp, owner, code/data/
config hashes, exact feature set, parameters, cost model, folds, benchmarks,
all results, and the reason accepted/rejected. Failed, informal, and highly
correlated variants still count; deleting a result does not delete a trial.

For the final candidate report:

- the [Deflated Sharpe Ratio](https://doi.org/10.3905/jpm.2014.40.5.094), using
  sample length, skew, kurtosis, variance across tested Sharpes, and the
  effective number of all trials;
- the [Probability of Backtest Overfitting](https://doi.org/10.21314/JCF.2016.322)
  from the frozen strategy-return matrix, alongside chronological walk-forward
  results; and
- White's Reality Check or an equivalent family-wise benchmark-superiority
  test over the complete candidate family.

Opening the final holdout retires it. Any subsequent model change receives a
new strategy ID and must collect a new untouched forward period.

## 7. Promotion gates

| Gate | Minimum evidence | Failure action |
|---|---|---|
| G0 — scaffold correctness | Deterministic publisher/snapshot/screen/simulator tests pass; labels obey sign invariants; timing, hash, cost, and cash behavior are explicit; no order/profit claim | Keep publisher plus offline scaffold only |
| G1 — decision-grade data readiness | At least 252 exchange sessions under the future raw-response metadata contract; complete point-in-time universe/prices; zero cutoff violations; missingness/revisions audited | V1 top-100 snapshots do not pass; continue collection and contract work |
| G2 — retrospective research | Positive net SPY/sector excess in concatenated walk-forward returns; DSR probability >95%; PBO <10%; survives 50 bp stress; not dominated by a benchmark or one name/regime | Reject or register a new hypothesis/trial |
| G3 — forward paper trading | Freeze code/config; at least 126 sessions of broker-independent paper fills; positive net excess after observed costs; drawdown/capacity within preregistered limits; no silent overrides | Extend/reject; any change restarts the gate |
| G4 — controlled live pilot | Separate explicit human authorization, legal/compliance review, broker security review, capital/daily-loss/kill-switch limits, monitoring, reconciliation, and rollback runbook | No live orders |

Passing a gate is necessary, not proof of future profit. G4 is not authorized by
this document or pull request.

## 8. Security and conduct boundary

Social inputs can be stale, incomplete, coordinated, or manipulated. The SEC's
[Social Media and Stock Tip Scams investor alert](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/social-media-stock-scams)
is a direct reason to penalize concentration, avoid illiquid/micro-cap names,
retain provenance, and never turn unverified discussion into a deterministic
trade claim. The research system must not publish positions before execution,
coordinate trading, ingest private customer data, or expose API/broker secrets.

## Current decision

**NO-GO for profitability claims and NO-GO for live trading.** The only supported
claim today is that the existing software publishes retail-sentiment summaries
and that its short retrospective archive does not establish a durable net edge.
The v1 screen and simulator are conservative research scaffolding only and do
not pass the decision-grade data or validation gates. The next authorized
activity is immutable data collection and offline paper research under this
protocol.
