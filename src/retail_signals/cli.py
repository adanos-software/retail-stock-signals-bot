"""Command-line entry point for generating daily Reddit post drafts."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from retail_signals.adanos import AdanosClient
from retail_signals.deepseek import DeepSeekClient, DeepSeekError
from retail_signals.render import render_post, render_title
from retail_signals.signals import (
    resolve_shared_narrative_explanations,
    select_daily_signals,
    tickers_requiring_explanations,
)


def main(argv: list[str] | None = None) -> int:
    """Run the post generator."""
    args = _parse_args(argv)
    api_key = args.api_key or os.getenv("ADANOS_API_KEY", "")
    if not api_key:
        print("ERROR: ADANOS_API_KEY is required.", file=sys.stderr)
        return 2

    now = datetime.now(ZoneInfo(args.timezone))
    date_label = args.date_label or now.strftime("%B %-d, %Y")
    date_slug = args.date or now.date().isoformat()
    client = AdanosClient(
        api_key=api_key,
        base_url=args.adanos_base_url,
        timeout=args.timeout,
        retries=args.retries,
    )

    trending_today = client.get_trending(days=1, limit=args.limit)
    trending_7d = client.get_trending(days=7, limit=args.limit)
    provisional = select_daily_signals(
        date_label=date_label,
        trending_today=trending_today,
        trending_7d=trending_7d,
    )

    explanations = {
        ticker: client.get_explanation(ticker)
        for ticker in tickers_requiring_explanations(provisional)
    }
    explanations = resolve_shared_narrative_explanations(provisional, explanations)
    signals = select_daily_signals(
        date_label=date_label,
        trending_today=trending_today,
        trending_7d=trending_7d,
        explanations=explanations,
    )

    ai_copy = None
    deepseek_key = args.deepseek_api_key or os.getenv("DEEPSEEK_API_KEY", "")
    if deepseek_key and not args.no_ai:
        try:
            ai_copy = DeepSeekClient(
                api_key=deepseek_key,
                base_url=args.deepseek_base_url,
                model=args.deepseek_model,
                timeout=args.timeout,
            ).generate_copy(signals)
        except DeepSeekError as exc:
            print(f"WARNING: DeepSeek disabled for this run: {exc}", file=sys.stderr)

    title = render_title(signals)
    post = render_post(signals, ai_copy=ai_copy)
    output = f"Title: {title}\n\n{post}"
    draft = _build_draft(
        title=title,
        body=post,
        date=date_slug,
        generated_at=now.isoformat(),
    )

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
        print(f"Wrote {output_path}")
    if args.posts_dir:
        posts_path = Path(args.posts_dir) / f"{date_slug}.md"
        posts_path.parent.mkdir(parents=True, exist_ok=True)
        posts_path.write_text(output, encoding="utf-8")
        print(f"Wrote {posts_path}")
    if args.drafts_dir:
        drafts_dir = Path(args.drafts_dir)
        daily_path = drafts_dir / f"{date_slug}.json"
        latest_path = drafts_dir / "latest-post.json"
        encoded = json.dumps(draft, ensure_ascii=False, indent=2) + "\n"
        drafts_dir.mkdir(parents=True, exist_ok=True)
        daily_path.write_text(encoded, encoding="utf-8")
        latest_path.write_text(encoded, encoding="utf-8")
        print(f"Wrote {daily_path}")
        print(f"Wrote {latest_path}")
    if not args.output and not args.posts_dir and not args.drafts_dir:
        print(output)

    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a Reddit daily stock signals post.")
    parser.add_argument("--output", help="Path to write the generated Markdown draft.")
    parser.add_argument("--posts-dir", help="Directory for dated Markdown post archives.")
    parser.add_argument("--drafts-dir", help="Directory for dated and latest JSON drafts.")
    parser.add_argument("--date", help="Machine date for archive files, e.g. 2026-05-04.")
    parser.add_argument("--date-label", help="Display date, e.g. 'May 4, 2026'.")
    parser.add_argument("--timezone", default="Europe/Berlin")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--api-key", help="Adanos API key. Prefer ADANOS_API_KEY.")
    parser.add_argument("--adanos-base-url", default="https://api.adanos.org")
    parser.add_argument("--deepseek-api-key", help="DeepSeek API key. Prefer DEEPSEEK_API_KEY.")
    parser.add_argument("--deepseek-base-url", default="https://api.deepseek.com")
    parser.add_argument("--deepseek-model", default="deepseek-chat")
    parser.add_argument("--no-ai", action="store_true", help="Disable DeepSeek polish.")
    return parser.parse_args(argv)


def _build_draft(*, title: str, body: str, date: str, generated_at: str) -> dict[str, str]:
    checksum = hashlib.sha256(f"{title}\n\n{body}".encode("utf-8")).hexdigest()
    return {
        "date": date,
        "subreddit": "RetailStockSignals",
        "title": title,
        "body": body,
        "checksum": checksum,
        "generated_at": generated_at,
    }


if __name__ == "__main__":
    raise SystemExit(main())
