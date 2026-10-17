"""Small DeepSeek API adapter with explicit, testable configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    timeout_seconds: float = 180.0
    max_tokens: int = 8192

    @classmethod
    def from_env(cls) -> "Settings":
        api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not set")
        base_url = os.environ.get("DEEPSEEK_BASE_URL", cls.base_url).strip().rstrip("/")
        model = os.environ.get("DEEPSEEK_MODEL", cls.model).strip()
        timeout_seconds = float(os.environ.get("DEEPSEEK_TIMEOUT_SECONDS", cls.timeout_seconds))
        max_tokens = int(os.environ.get("DEEPSEEK_MAX_TOKENS", cls.max_tokens))
        if not base_url.startswith("https://"):
            raise RuntimeError("DEEPSEEK_BASE_URL must use HTTPS")
        if not model:
            raise RuntimeError("DEEPSEEK_MODEL must not be empty")
        if not 1 <= max_tokens <= 131_072:
            raise RuntimeError("DEEPSEEK_MAX_TOKENS must be between 1 and 131072")
        if not 1 <= timeout_seconds <= 600:
            raise RuntimeError("DEEPSEEK_TIMEOUT_SECONDS must be between 1 and 600")
        return cls(api_key, base_url, model, timeout_seconds, max_tokens)


class DeepSeekClient:
    def __init__(self, settings: Settings | None = None, client: Any | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self._client = client or self._new_client()

    def _new_client(self) -> Any:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise RuntimeError("Missing dependency: run `python scripts/setup.py`") from exc
        return AsyncOpenAI(
            api_key=self.settings.api_key,
            base_url=self.settings.base_url,
            timeout=self.settings.timeout_seconds,
            max_retries=2,
        )

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str = "",
        thinking: bool = True,
        max_tokens: int | None = None,
        reasoning_effort: str = "",
    ) -> dict[str, Any]:
        selected_model = model.strip() or self.settings.model
        selected_max_tokens = self.settings.max_tokens if max_tokens is None else max_tokens
        if not 1 <= selected_max_tokens <= 131_072:
            raise ValueError("max_tokens must be between 1 and 131072")
        effort = reasoning_effort.strip() or ("max" if thinking else "off")
        if effort not in {"off", "low", "high", "max"}:
            raise ValueError("reasoning_effort must be off, low, high, or max")
        if not thinking and effort != "off":
            raise ValueError("thinking=False requires reasoning_effort=off")

        try:
            response = await self._client.chat.completions.create(
                model=selected_model,
                messages=messages,
                max_tokens=selected_max_tokens,
                stream=False,
                reasoning_effort="none" if effort == "off" else effort,
                extra_body={"thinking": {"type": "disabled" if effort == "off" else "enabled"}},
            )
        except Exception as exc:
            raise RuntimeError(f"DeepSeek request failed: {type(exc).__name__}: {exc}") from exc

        choice = response.choices[0]
        usage = getattr(response, "usage", None)
        return {
            "model": getattr(response, "model", selected_model),
            "requested_reasoning_effort": effort,
            "content": choice.message.content or "",
            "finish_reason": getattr(choice, "finish_reason", None),
            "usage": {
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
                "cache_hit_tokens": getattr(usage, "prompt_cache_hit_tokens", None),
                "cache_miss_tokens": getattr(usage, "prompt_cache_miss_tokens", None),
            },
        }
