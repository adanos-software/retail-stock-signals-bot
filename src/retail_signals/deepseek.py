"""Optional DeepSeek polish for Reddit post prose."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib import error, request

from retail_signals.signals import DailySignals


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
                        "You write concise Reddit market-sentiment briefs. "
                        "Use only the supplied facts. Do not invent causes, prices, "
                        "recommendations, or financial advice. Return valid JSON only."
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
            decoded = json.loads(content)
            return AiCopy(
                intro=_clean_text(decoded["intro"], max_chars=360),
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
        "task": {
            "intro": "one sentence: top buzz, cleanest sentiment breakout, biggest breakout, biggest fade",
            "takeaway": "2-3 concise sentences focused on buzz/sentiment context",
            "question": "one engagement question comparing 2-3 signals",
        },
        "constraints": [
            "No buy/sell/hold language",
            "No price predictions",
            "Mention that a shared narrative is shared when explanations overlap",
            "Keep wording plain and Reddit-native",
        ],
        "signals": asdict(signals),
    }


def _clean_text(value: Any, *, max_chars: int) -> str:
    if not isinstance(value, str):
        raise DeepSeekError("DeepSeek field is not a string")
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        raise DeepSeekError("DeepSeek field is empty")
    return cleaned[:max_chars].rstrip()
