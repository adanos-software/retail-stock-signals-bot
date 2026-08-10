"""Optional DeepSeek polish for Reddit post prose."""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from http.client import HTTPException
from typing import Any
from urllib import error, parse, request

from retail_signals.adanos import _retry_after_seconds
from retail_signals.signals import DailySignals, StockSignal

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
_RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}
_DIRECT_ADVICE_RE = re.compile(
    r"\b(?:buy|sell|hold|target|will)\b|\bprice\s+estimate\b",
    flags=re.IGNORECASE,
)


class DeepSeekError(RuntimeError):
    """Raised when the optional AI prose generation fails."""


@dataclass(frozen=True)
class AiCopy:
    """Structured prose that can safely be inserted into the renderer."""

    takeaway: str
    signal_reads: dict[str, str]


@dataclass(frozen=True)
class DeepSeekClient:
    """OpenAI-compatible DeepSeek chat client."""

    api_key: str
    base_url: str = DEFAULT_DEEPSEEK_BASE_URL
    model: str = "deepseek-chat"
    timeout: float = 45.0
    retries: int = 1
    retry_sleep: float = 1.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.timeout, bool)
            or not isinstance(self.timeout, (int, float))
            or not math.isfinite(self.timeout)
            or self.timeout <= 0
        ):
            raise ValueError("timeout must be a positive finite number")
        if isinstance(self.retries, bool) or not isinstance(self.retries, int):
            raise ValueError("retries must be an integer")
        if self.retries < 0:
            raise ValueError("retries must not be negative")
        if (
            isinstance(self.retry_sleep, bool)
            or not isinstance(self.retry_sleep, (int, float))
            or not math.isfinite(self.retry_sleep)
            or self.retry_sleep < 0
        ):
            raise ValueError("retry_sleep must be a nonnegative finite number")
        _validate_base_url(self.base_url)

    def generate_copy(self, signals: DailySignals) -> AiCopy:
        """Generate compact Reddit copy from deterministic signal facts."""
        payload = {
            "model": self.model,
            "temperature": 0.4,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You edit concise Reddit market-sentiment briefs. Use only "
                        "hard_facts, allowed_interpretations, and unverified_context. "
                        "Treat unverified_context as Reddit discussion context, not verified "
                        "fact. Do not add causes, prices, recommendations, or financial advice. "
                        "Return valid JSON only."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        _prompt_payload(signals), separators=(",", ":")
                    ),
                },
            ],
        }
        data = self._post_json("/chat/completions", payload)
        try:
            content = data["choices"][0]["message"]["content"]
            decoded = _loads_json_object(content)
            takeaway = _clean_optional_text(decoded.get("takeaway"), max_chars=520)
            signal_reads = _clean_signal_reads(
                decoded.get("signal_reads"),
                expected=list(_selected_signal_roles(signals)),
            )
            if not takeaway and not signal_reads:
                raise DeepSeekError("DeepSeek returned no usable copy")
            return AiCopy(takeaway=takeaway, signal_reads=signal_reads)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise DeepSeekError("DeepSeek returned an invalid JSON response") from exc

    def _post_json(self, path: str, payload: dict[str, Any]) -> Any:
        url = f"{self.base_url.rstrip('/')}{path}"
        try:
            encoded = json.dumps(payload).encode("utf-8")
        except (TypeError, ValueError, UnicodeError) as exc:
            raise DeepSeekError(f"DeepSeek request setup failed: {exc}") from exc
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        last_error: Exception | None = None

        for attempt in range(self.retries + 1):
            retry_delay: float | None = None
            try:
                api_request = request.Request(
                    url, data=encoded, headers=headers, method="POST"
                )
                with request.urlopen(api_request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except error.HTTPError as exc:
                retry_after = (
                    exc.headers.get("Retry-After") if exc.headers is not None else None
                )
                try:
                    try:
                        body = exc.read().decode("utf-8", errors="replace")
                    except (HTTPException, OSError) as body_error:
                        body = (
                            f"<response body unavailable: {type(body_error).__name__}>"
                        )
                finally:
                    exc.close()
                if self.api_key:
                    body = body.replace(self.api_key, "[REDACTED]")
                last_error = DeepSeekError(
                    f"HTTP {exc.code} from DeepSeek: {body[:300]}"
                )
                if exc.code not in _RETRYABLE_HTTP_STATUSES:
                    break
                if retry_after is not None:
                    retry_delay = _retry_after_seconds(retry_after)
            except json.JSONDecodeError as exc:
                last_error = exc
            except (
                HTTPException,
                OSError,
                TimeoutError,
                UnicodeError,
                error.URLError,
            ) as exc:
                last_error = exc
            except (TypeError, ValueError) as exc:
                last_error = exc
                break

            if attempt < self.retries:
                delay = (
                    retry_delay
                    if retry_delay is not None
                    else self.retry_sleep * (attempt + 1)
                )
                time.sleep(delay)

        raise DeepSeekError(f"DeepSeek request failed: {last_error}") from last_error


def _prompt_payload(signals: DailySignals) -> dict[str, Any]:
    selected = _selected_signal_roles(signals)
    signal_read_descriptions = {
        "top_buzz": "1 sentence analyzing top_buzz using metrics and Reddit context",
        "cleanest_breakout": (
            "1 sentence analyzing cleanest_breakout using metrics and Reddit context"
        ),
        "biggest_breakout": (
            "1 sentence analyzing biggest_breakout using metrics and Reddit context"
        ),
        "biggest_fade": "1 sentence analyzing biggest_fade using metrics and Reddit context",
    }
    return {
        "output_schema": {
            "takeaway": "2-3 concise sentences focused on buzz/sentiment context",
            "signal_reads": {role: signal_read_descriptions[role] for role in selected},
        },
        "style": _style_profile(signals.date_label),
        "constraints": [
            "No buy/sell/hold language",
            "No price predictions",
            "Use only hard_facts and allowed_interpretations",
            "You may use unverified_context only with soft framing such as Reddit discussion points to",
            "Do not state causal claims as fact",
            "For signal_reads, synthesize the metrics and Reddit context into one readable analysis sentence",
            "Do not repeat exact buzz scores, buzz deltas, sentiment scores, or bull/bear percentages in prose",
            "Explain the tension between attention, sentiment, and context instead of restating facts",
            "Do not repeat the metric line or start signal_reads with Context:",
            "Sound like a professional market desk note, not a hype post and not generic AI copy",
            "Use compact sentence structure and avoid generic AI phrasing",
            "Avoid stale phrases such as today's signal, stands out, cleanest signal, worth watching, and only time will tell",
            "Avoid hype or trading-framing words such as squeeze, trigger, sharp decline, sparking optimism, setup, play, entry, exit, target, conviction, or compelling",
            "If a selected ticker is obscure, use company_name for one short identifying phrase",
            "Keep wording plain and Reddit-native",
        ],
        "hard_facts": _hard_facts(signals),
        "allowed_interpretations": _allowed_interpretations(signals),
        "unverified_context": _unverified_context(signals),
    }


def _clean_text(value: Any, *, max_chars: int) -> str:
    if not isinstance(value, str):
        raise DeepSeekError("DeepSeek field is not a string")
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        raise DeepSeekError("DeepSeek field is empty")
    cleaned = _replace_trading_framing(cleaned)
    cleaned = _soften_claim_language(cleaned)
    cleaned = _remove_metric_restatement(cleaned)
    if _contains_blocked_claim_language(cleaned):
        raise DeepSeekError("DeepSeek field contains blocked claim language")
    return cleaned[:max_chars].rstrip()


def _clean_optional_text(value: Any, *, max_chars: int) -> str:
    try:
        return _clean_text(value, max_chars=max_chars)
    except DeepSeekError:
        return ""


def _clean_signal_reads(
    value: Any,
    *,
    expected: list[str] | None = None,
) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}

    if expected is None:
        expected = ["top_buzz", "cleanest_breakout", "biggest_breakout", "biggest_fade"]
    cleaned: dict[str, str] = {}
    for key in expected:
        field = _clean_optional_text(value.get(key), max_chars=260)
        if field:
            cleaned[key] = field
    return cleaned


def _hard_facts(signals: DailySignals) -> dict[str, Any]:
    selected = _selected_signal_roles(signals)
    return {
        "date_label": signals.date_label,
        "selected": {name: _signal_facts(signal) for name, signal in selected.items()},
        "top_buzz_list": [_signal_facts(signal) for signal in signals.top_buzz_list],
        "movers": [_signal_facts(signal) for signal in signals.movers],
    }


def _signal_facts(signal: StockSignal) -> dict[str, Any]:
    return {
        "ticker": signal.ticker,
        "buzz_score": signal.buzz_score,
        "sentiment_label": signal.sentiment_label,
        "sentiment_score": signal.sentiment_score,
        "bullish_pct": signal.bullish_pct,
        "bearish_pct": signal.bearish_pct,
        "trend": signal.trend,
        "buzz_delta_7d": signal.buzz_delta_7d,
        "buzz_start_7d": signal.buzz_start_7d,
        "buzz_end_7d": signal.buzz_end_7d,
    }


def _allowed_interpretations(signals: DailySignals) -> list[str]:
    interpretations = [
        f"{signals.top_buzz.ticker} leads on absolute buzz score.",
    ]
    if signals.cleanest_breakout is not None:
        interpretations.append(
            f"{signals.cleanest_breakout.ticker} has the cleanest sentiment profile."
        )
    if signals.biggest_breakout is not None:
        interpretations.append(
            f"{signals.biggest_breakout.ticker} has the largest 7-day buzz expansion."
        )
    else:
        interpretations.append("No selected ticker has a positive 7-day buzz delta.")
    if signals.biggest_fade is not None:
        interpretations.append(f"{signals.biggest_fade.ticker} is the main 7-day fade.")
    else:
        interpretations.append("No selected ticker has a negative 7-day buzz delta.")
    if signals.top_buzz.trend == "falling":
        interpretations.append(
            f"{signals.top_buzz.ticker} is sustained attention rather than fresh acceleration."
        )
    return interpretations


def _unverified_context(signals: DailySignals) -> dict[str, str]:
    selected = _selected_signal_roles(signals).values()
    return {
        signal.ticker: signal.explanation for signal in selected if signal.explanation
    }


def _selected_signal_roles(signals: DailySignals) -> dict[str, StockSignal]:
    """Return only signal roles whose directional invariants are satisfied."""
    selected = {"top_buzz": signals.top_buzz}
    if signals.cleanest_breakout is not None:
        selected["cleanest_breakout"] = signals.cleanest_breakout
    if signals.biggest_breakout is not None:
        selected["biggest_breakout"] = signals.biggest_breakout
    if signals.biggest_fade is not None:
        selected["biggest_fade"] = signals.biggest_fade
    return selected


def _loads_json_object(content: Any) -> dict[str, Any]:
    """Parse model JSON, tolerating fenced or prefixed JSON output."""
    if not isinstance(content, str):
        raise DeepSeekError("DeepSeek response content is not a string")
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        decoded = json.loads(stripped[start : end + 1])

    if not isinstance(decoded, dict):
        raise DeepSeekError("DeepSeek JSON response is not an object")
    return decoded


def _style_profile(date_label: str) -> dict[str, str]:
    """Rotate prose framing deterministically so daily drafts do not feel templated."""
    profiles = [
        {
            "name": "market_desk",
            "takeaway_shape": "Explain what is driving attention, where sentiment confirms it, and where it conflicts.",
        },
        {
            "name": "signal_brief",
            "takeaway_shape": "Separate attention from sentiment and call out shared narratives when relevant.",
        },
        {
            "name": "flow_context",
            "takeaway_shape": "Focus on buzz direction, sentiment tilt, and whether context supports the move.",
        },
    ]
    return profiles[sum(date_label.encode("utf-8")) % len(profiles)]


def _replace_trading_framing(text: str) -> str:
    """Remove common trading-call phrasing from otherwise usable model copy."""
    replacements = {
        "M&A play": "M&A narrative",
        "m&a play": "M&A narrative",
        "acquisition play": "acquisition narrative",
        "squeeze setup": "squeeze narrative",
        "short squeeze": "short-interest narrative",
        "short-squeeze": "short-interest",
        "potential trigger": "possible catalyst",
        "trigger": "catalyst",
        "sharp decline": "downside concern",
        "sparking optimism": "adding optimism",
        "sparked optimism": "added optimism",
        "surged": "rose",
        "trade setup": "market signal",
        "trading setup": "market signal",
        "entry point": "signal point",
        "price target": "price estimate",
    }
    cleaned = text
    for source, target in replacements.items():
        cleaned = cleaned.replace(source, target)
    return cleaned


def _soften_claim_language(text: str) -> str:
    """Convert hard causal phrasing into softer Reddit-context phrasing."""
    replacements = {
        " because ": " as ",
        " after ": " around ",
        " following ": " around ",
        " driven by ": " tied to ",
        " fueled by ": " tied to ",
        " sparked by ": " tied to ",
    }
    cleaned = text
    for source, target in replacements.items():
        cleaned = cleaned.replace(source, target)
    return cleaned


def _remove_metric_restatement(text: str) -> str:
    """Strip exact metric restatements that duplicate the line above."""
    cleaned = text
    patterns = [
        r"\s+to\s+\d+(?:\.\d+)?\b",
        r"\s+\d+(?:\.\d+)?\s+points?\b",
        r"\s+by\s+\d+(?:\.\d+)?\s+points?\b",
        r"\s+with\s+(?:strong positive|positive|neutral|negative|strong negative)\s+sentiment\b",
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split())


def _contains_blocked_claim_language(text: str) -> bool:
    if _DIRECT_ADVICE_RE.search(text):
        return True
    lowered = text.lower()
    blocked = [
        " market cap",
        " passed nvidia",
        " ambiguous",
        " cleanup",
        " cleaned",
        " filter",
        " filtered",
        " squeeze",
        " trigger",
        " sharp decline",
        " sparking optimism",
    ]
    return any(fragment in lowered for fragment in blocked)


def _validate_base_url(value: Any) -> None:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise DeepSeekError("DeepSeek base_url must be an absolute HTTP(S) URL")
    try:
        parsed = parse.urlsplit(value)
        _port = parsed.port
    except ValueError as exc:
        raise DeepSeekError(
            "DeepSeek base_url must be an absolute HTTP(S) URL"
        ) from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise DeepSeekError(
            "DeepSeek base_url must be HTTP(S) without credentials, query, or fragment"
        )
