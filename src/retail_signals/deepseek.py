"""Optional DeepSeek polish for Reddit post prose."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from retail_signals.signals import DailySignals, StockSignal


DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class DeepSeekError(RuntimeError):
    """Raised when the optional AI prose generation fails."""


@dataclass(frozen=True)
class AiCopy:
    """Structured prose that can safely be inserted into the renderer."""

    intro: str
    takeaway: str
    question: str


@dataclass(frozen=True)
class DeepSeekClient:
    """OpenAI-compatible DeepSeek chat client."""

    api_key: str
    base_url: str = DEFAULT_DEEPSEEK_BASE_URL
    model: str = "deepseek-chat"
    timeout: float = 45.0
    retries: int = 1
    retry_sleep: float = 1.0

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
                        "hard_facts and allowed_interpretations. Treat unverified_context "
                        "as optional Reddit discussion context, not truth. Do not add "
                        "causes, news, deals, lawsuits, prices, recommendations, or "
                        "financial advice. Return valid JSON only."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(_prompt_payload(signals), separators=(",", ":")),
                },
            ],
        }
        data = self._post_json("/chat/completions", payload)
        try:
            content = data["choices"][0]["message"]["content"]
            decoded = _loads_json_object(content)
            return AiCopy(
                intro=_clean_text(decoded.get("intro", decoded.get("task")), max_chars=360),
                takeaway=_clean_text(decoded["takeaway"], max_chars=520),
                question=_clean_text(decoded["question"], max_chars=180),
            )
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise DeepSeekError("DeepSeek returned an invalid JSON response") from exc

    def _post_json(self, path: str, payload: dict[str, Any]) -> Any:
        url = f"{self.base_url.rstrip('/')}{path}"
        encoded = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        last_error: Exception | None = None

        for attempt in range(self.retries + 1):
            try:
                api_request = request.Request(url, data=encoded, headers=headers, method="POST")
                with request.urlopen(api_request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                last_error = DeepSeekError(f"HTTP {exc.code} from DeepSeek: {body[:300]}")
                if exc.code not in {429, 500, 502, 503, 504}:
                    break
            except (TimeoutError, error.URLError, json.JSONDecodeError) as exc:
                last_error = exc

            if attempt < self.retries:
                time.sleep(self.retry_sleep * (attempt + 1))

        raise DeepSeekError(f"DeepSeek request failed: {last_error}") from last_error


def _prompt_payload(signals: DailySignals) -> dict[str, Any]:
    return {
        "output_schema": {
            "intro": "one sentence: top buzz, cleanest sentiment breakout, biggest breakout, biggest fade",
            "takeaway": "2-3 concise sentences focused on buzz/sentiment context",
            "question": "one engagement question comparing 2-3 signals",
        },
        "style": _style_profile(signals.date_label),
        "constraints": [
            "No buy/sell/hold language",
            "No price predictions",
            "Use only hard_facts and allowed_interpretations",
            "Treat unverified_context as optional context, not verified truth",
            "Do not state causal claims as fact",
            "Do not mention external news, deals, lawsuits, earnings, market-cap milestones, or partnerships",
            "Sound like a professional market desk note, not a hype post and not generic AI copy",
            "Avoid repeating the same sentence structure across intro, takeaway, and question",
            "Avoid stale phrases such as today's signal, stands out, cleanest signal, worth watching, and only time will tell",
            "Avoid trading-framing words such as setup, play, entry, exit, target, conviction, or compelling",
            "Mention that a shared narrative is shared when explanations overlap",
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
    if _contains_blocked_claim_language(cleaned):
        raise DeepSeekError("DeepSeek field contains blocked claim language")
    return cleaned[:max_chars].rstrip()


def _hard_facts(signals: DailySignals) -> dict[str, Any]:
    selected = {
        "top_buzz": signals.top_buzz,
        "cleanest_breakout": signals.cleanest_breakout,
        "biggest_breakout": signals.biggest_breakout,
        "biggest_fade": signals.biggest_fade,
    }
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
        f"{signals.cleanest_breakout.ticker} has the cleanest sentiment profile.",
        f"{signals.biggest_breakout.ticker} has the largest 7-day buzz expansion.",
        f"{signals.biggest_fade.ticker} is the main 7-day fade.",
    ]
    if signals.top_buzz.trend == "falling":
        interpretations.append(
            f"{signals.top_buzz.ticker} is sustained attention rather than fresh acceleration."
        )
    return interpretations


def _unverified_context(signals: DailySignals) -> dict[str, str]:
    selected = [
        signals.top_buzz,
        signals.cleanest_breakout,
        signals.biggest_breakout,
        signals.biggest_fade,
    ]
    return {signal.ticker: signal.explanation for signal in selected if signal.explanation}


def _loads_json_object(content: str) -> dict[str, Any]:
    """Parse model JSON, tolerating fenced or prefixed JSON output."""
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
            "intro_shape": "Lead with the dominant narrative, then contrast momentum and fade names.",
            "takeaway_shape": "Explain what is driving attention, where sentiment confirms it, and where it conflicts.",
            "question_shape": "Ask readers to compare narrative quality rather than predict prices.",
        },
        {
            "name": "signal_brief",
            "intro_shape": "Start with the highest-buzz ticker, then name the strongest sentiment and fade signals.",
            "takeaway_shape": "Separate attention from sentiment and call out shared narratives when relevant.",
            "question_shape": "Ask which data signal looks most meaningful.",
        },
        {
            "name": "flow_context",
            "intro_shape": "Frame the post around what retail attention is rotating toward and away from.",
            "takeaway_shape": "Focus on buzz direction, sentiment tilt, and whether context supports the move.",
            "question_shape": "Ask readers which narrative has the cleaner data behind it.",
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
        "trade setup": "market signal",
        "trading setup": "market signal",
        "entry point": "signal point",
        "price target": "price estimate",
    }
    cleaned = text
    for source, target in replacements.items():
        cleaned = cleaned.replace(source, target)
    return cleaned


def _contains_blocked_claim_language(text: str) -> bool:
    lowered = text.lower()
    blocked = [
        " because ",
        " after ",
        " following ",
        " driven by ",
        " fueled by ",
        " sparked by ",
        " deal",
        " settlement",
        " lawsuit",
        " earnings",
        " market cap",
        " passed nvidia",
        " will ",
        " buy ",
        " sell ",
        " target",
    ]
    return any(fragment in lowered for fragment in blocked)
