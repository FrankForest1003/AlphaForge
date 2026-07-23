from __future__ import annotations

import json
from typing import Any

from openai import OpenAI


class DeepSeekJSONClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        thinking_enabled: bool,
        client: Any | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("API_KEY is required")
        if not base_url:
            raise ValueError("BASE_URL is required")
        if not model:
            raise ValueError("MODEL is required")
        self.model = model
        self.thinking_enabled = thinking_enabled
        self.client = client or OpenAI(api_key=api_key, base_url=base_url)

    def health(self) -> dict[str, Any]:
        return {
            "provider": "DeepSeek",
            "model": self.model,
            "thinking_enabled": self.thinking_enabled,
        }

    def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        empty_error: str,
        invalid_error: str,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "max_tokens": max_tokens,
        }
        if self.thinking_enabled:
            request["reasoning_effort"] = "high"
            request["extra_body"] = {"thinking": {"type": "enabled"}}
        else:
            request["extra_body"] = {"thinking": {"type": "disabled"}}

        response = self.client.chat.completions.create(**request)
        content = response.choices[0].message.content
        if not content:
            raise ValueError(empty_error)
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(invalid_error) from exc
        if not isinstance(payload, dict):
            raise ValueError(invalid_error)

        usage = getattr(response, "usage", None)
        return {
            "payload": payload,
            "usage": {
                "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
                "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
            },
        }
