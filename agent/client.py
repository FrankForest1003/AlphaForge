from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    """Convert an OpenAI SDK response into JSON without losing response fields."""

    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "__dict__"):
        return {
            str(key): _json_safe(item)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class DeepSeekCallError(ValueError):
    """A failed model call together with the safe request/response trace."""

    def __init__(self, message: str, *, trace: dict[str, Any]) -> None:
        super().__init__(message)
        self.trace = trace


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
        self.base_url = base_url
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
        trace_context: dict[str, Any],
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

        started_at = _utc_now()
        started_clock = time.perf_counter()
        trace: dict[str, Any] = {
            "provider": "DeepSeek",
            "base_url": self.base_url,
            "started_at": started_at,
            "finished_at": None,
            "duration_ms": None,
            "request_parameters": _json_safe(
                {key: value for key, value in request.items() if key != "messages"}
            ),
            "dynamic_context": _json_safe(trace_context),
            "raw_response": None,
            "response_content": None,
            "parsed_payload": None,
            "usage": {},
            "error": None,
        }

        try:
            response = self.client.chat.completions.create(**request)
            trace["raw_response"] = _json_safe(response)
            content = response.choices[0].message.content
            trace["response_content"] = content
        except Exception as exc:
            trace["finished_at"] = _utc_now()
            trace["duration_ms"] = round(
                (time.perf_counter() - started_clock) * 1000,
                3,
            )
            trace["error"] = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
            raise DeepSeekCallError(str(exc), trace=trace) from exc

        usage = getattr(response, "usage", None)
        trace["usage"] = {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        }
        trace["finished_at"] = _utc_now()
        trace["duration_ms"] = round(
            (time.perf_counter() - started_clock) * 1000,
            3,
        )
        if not content:
            trace["error"] = {"type": "empty_response", "message": empty_error}
            raise DeepSeekCallError(empty_error, trace=trace)
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            trace["error"] = {"type": "invalid_json", "message": invalid_error}
            raise DeepSeekCallError(invalid_error, trace=trace) from exc
        if not isinstance(payload, dict):
            trace["error"] = {"type": "invalid_json", "message": invalid_error}
            raise DeepSeekCallError(invalid_error, trace=trace)

        trace["parsed_payload"] = payload
        return {
            "payload": payload,
            "usage": trace["usage"],
            "trace": trace,
        }
