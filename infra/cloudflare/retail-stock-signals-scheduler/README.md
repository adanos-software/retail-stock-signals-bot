# Adanos Retail Stock Signals Scheduler

Dedicated Cloudflare Worker for triggering the daily `retail-stock-signals-bot` GitHub Actions workflow.

## Separation

- Cloudflare Worker name: `adanos-retail-stock-signals-scheduler`
- Cloudflare account: `Adanos Software`
- Public route: disabled with `workers_dev = false`
- Trigger type: Cloudflare Cron only
- Target workflow: `adanos-software/retail-stock-signals-bot/.github/workflows/daily-publish.yml`

## Schedule

Cloudflare Cron uses UTC. Two cron entries are configured to cover Berlin daylight saving time:

- `0 18 * * *` for 20:00 Europe/Berlin during CEST
- `0 19 * * *` for 20:00 Europe/Berlin during CET

The Worker checks the actual Europe/Berlin local time and dispatches only at 20:00, skipping the duplicate seasonal slot.

## Required Secret

Set `GITHUB_TOKEN` in Cloudflare before relying on the scheduler:

```bash
npx wrangler secret put GITHUB_TOKEN
```

Use a fine-grained GitHub token scoped only to `adanos-software/retail-stock-signals-bot` with `Actions: Read and write`.

## Deploy

```bash
npm install
npm run typecheck
npm run deploy
```
