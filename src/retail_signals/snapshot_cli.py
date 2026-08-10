"""Capture immutable, closed-day Adanos research snapshots."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from retail_signals import __version__
from retail_signals.adanos import (
    AdanosApiError,
    AdanosClient,
    parse_retries,
    parse_timeout,
    parse_trending_limit,
    validate_base_url,
)
from retail_signals.research import capture_closed_snapshot, write_snapshot


def main(argv: list[str] | None = None) -> int:
    """Capture one completed UTC day; never fetch today for research."""
    args = _parse_args(argv)
    api_access = os.getenv("ADANOS_API_KEY", "")
    if not api_access:
        print("ERROR: ADANOS_API_KEY is required.", file=sys.stderr)
        return 2

    request_started_at = datetime.now(UTC)
    window_end = args.window_end or request_started_at.date() - timedelta(days=1)
    try:
        client = AdanosClient(
            api_key=api_access,
            base_url=args.adanos_base_url,
            timeout=args.timeout,
            retries=args.retries,
        )
        snapshot = capture_closed_snapshot(
            client,
            window_end=window_end,
            limit=args.limit,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except AdanosApiError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    output_path = Path(args.output)
    try:
        write_snapshot(snapshot, output_path)
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        f"Wrote {output_path} ({len(snapshot.rows)} rows, "
        f"sha256={snapshot.content_sha256})"
    )
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture one completed UTC day of Adanos Reddit stock features."
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--output", required=True, help="New JSON snapshot path.")
    parser.add_argument(
        "--window-end",
        type=date.fromisoformat,
        help="Completed UTC date (YYYY-MM-DD); defaults to yesterday.",
    )
    parser.add_argument(
        "--limit",
        type=parse_trending_limit,
        default=100,
        help="Rows to capture (1-100).",
    )
    parser.add_argument("--timeout", type=parse_timeout, default=30.0)
    parser.add_argument("--retries", type=parse_retries, default=2)
    parser.add_argument(
        "--adanos-base-url",
        type=_parse_base_url,
        default="https://api.adanos.org",
    )
    return parser.parse_args(argv)


def _parse_base_url(value: str) -> str:
    try:
        return validate_base_url(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
