"""Command-line entry point for generating daily Reddit post drafts."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from retail_signals import __version__
from retail_signals.adanos import (
    AdanosApiError,
    AdanosClient,
    parse_retries,
    parse_timeout,
    parse_trending_limit,
    validate_base_url,
)
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

    try:
        return _run(args, api_key)
    except (AdanosApiError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _run(args: argparse.Namespace, api_key: str) -> int:
    """Generate one draft after argparse and credential validation."""

    date_label = args.date_label or datetime.now(ZoneInfo(args.timezone)).strftime(
        "%B %-d, %Y"
    )
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

    explanations: dict[str, str] = {}
    for ticker in tickers_requiring_explanations(provisional):
        try:
            explanations[ticker] = client.get_explanation(ticker)
        except AdanosApiError as exc:
            explanations[ticker] = ""
            print(
                f"WARNING: Adanos explanation unavailable for {ticker}: {exc}",
                file=sys.stderr,
            )
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

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
        print(f"Wrote {output_path}")
    else:
        print(output)

    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a Reddit daily stock signals post."
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--output", help="Path to write the generated Markdown draft.")
    parser.add_argument("--date-label", help="Display date, e.g. 'May 4, 2026'.")
    parser.add_argument("--timezone", type=_parse_timezone, default="Europe/Berlin")
    parser.add_argument("--limit", type=parse_trending_limit, default=50)
    parser.add_argument("--timeout", type=parse_timeout, default=30.0)
    parser.add_argument("--retries", type=parse_retries, default=2)
    parser.add_argument("--api-key", help="Adanos API key. Prefer ADANOS_API_KEY.")
    parser.add_argument(
        "--adanos-base-url",
        type=_parse_base_url,
        default="https://api.adanos.org",
    )
    parser.add_argument(
        "--deepseek-api-key", help="DeepSeek API key. Prefer DEEPSEEK_API_KEY."
    )
    parser.add_argument(
        "--deepseek-base-url",
        type=_parse_base_url,
        default="https://api.deepseek.com",
    )
    parser.add_argument("--deepseek-model", default="deepseek-chat")
    parser.add_argument("--no-ai", action="store_true", help="Disable DeepSeek polish.")
    return parser.parse_args(argv)


def _parse_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise argparse.ArgumentTypeError(
            "timezone must be a valid IANA timezone"
        ) from exc
    return value


def _parse_base_url(value: str) -> str:
    try:
        return validate_base_url(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
