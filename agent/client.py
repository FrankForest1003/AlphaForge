from __future__ import annotations

import json
import re
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


def _decode_json_value(content: str, key: str) -> Any:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*', content)
    if not match:
        raise ValueError(f"missing JSON key: {key}")
    return json.JSONDecoder().raw_decode(content, match.end())[0]


def _decode_source_string(content: str) -> str:
    match = re.search(r'"source_code"\s*:\s*"', content)
    if not match:
        raise ValueError("missing JSON source_code string")
    encoded = content[match.end():]

    escaped = False
    closing_index: int | None = None
    for index, character in enumerate(encoded):
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character == '"':
            closing_index = index
            break
    if closing_index is not None:
        encoded = encoded[:closing_index]
    try:
        return json.loads(f'"{encoded}"')
    except json.JSONDecodeError as exc:
        raise ValueError("source_code JSON string could not be recovered") from exc


def recover_known_payload(content: str) -> dict[str, Any] | None:
    """Recover a complete known payload when a model omits only outer JSON closure."""

    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)

    try:
        source_code = _decode_source_string(stripped)
        if '"design"' in stripped:
            design = _decode_json_value(stripped, "design")
            return {"design": design, "source_code": source_code}
        if '"change_summary"' in stripped and '"first_interrupted_stage"' in stripped:
            return {
                "change_summary": _decode_json_value(stripped, "change_summary"),
                "first_interrupted_stage": _decode_json_value(
                    stripped,
                    "first_interrupted_stage",
                ),
                "source_code": source_code,
            }
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return None


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
        max_attempts: int = 2,
    ) -> dict[str, Any]:
        if max_attempts not in {1, 2}:
            raise ValueError("max_attempts must be 1 or 2")
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
            "attempts": [],
        }

        total_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        payload: dict[str, Any] | None = None
        last_parse_error: Exception | None = None
        previous_parse_failure = False
        for attempt_index in range(max_attempts):
            attempt_request = dict(request)
            if attempt_index:
                # Empty structured output is commonly caused by a reasoning response
                # exhausting its output budget. Retry once without hidden reasoning.
                attempt_request.pop("reasoning_effort", None)
                attempt_request["extra_body"] = {"thinking": {"type": "disabled"}}
                if previous_parse_failure:
                    attempt_request["messages"] = [
                        *messages,
                        {
                            "role": "user",
                            "content": (
                                "The previous response was not valid JSON. Return the "
                                "same requested object again as strict JSON. Encode the "
                                "complete Python source as the source_code JSON string; "
                                "do not omit its closing quote or the outer braces."
                            ),
                        },
                    ]
            try:
                response = self.client.chat.completions.create(**attempt_request)
                safe_response = _json_safe(response)
                content = response.choices[0].message.content
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
            attempt_usage = {
                "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                "completion_tokens": int(
                    getattr(usage, "completion_tokens", 0) or 0
                ),
                "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
            }
            for key in total_usage:
                total_usage[key] += attempt_usage[key]

            attempt_trace = {
                "attempt": attempt_index + 1,
                "thinking_enabled": bool(
                    attempt_request.get("extra_body", {})
                    .get("thinking", {})
                    .get("type")
                    == "enabled"
                ),
                "raw_response": safe_response,
                "response_content": content,
                "usage": attempt_usage,
                "parse_mode": None,
                "error": None,
            }
            trace["attempts"].append(attempt_trace)
            trace["raw_response"] = safe_response
            trace["response_content"] = content
            trace["usage"] = total_usage

            if not content:
                attempt_trace["error"] = {
                    "type": "empty_response",
                    "message": empty_error,
                }
                trace["error"] = attempt_trace["error"]
                continue
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as exc:
                last_parse_error = exc
                recovered = recover_known_payload(content)
                if recovered is not None:
                    payload = recovered
                    attempt_trace["parse_mode"] = "recovered_known_payload"
                    trace["error"] = None
                    break
                previous_parse_failure = True
                attempt_trace["error"] = {
                    "type": "invalid_json",
                    "message": invalid_error,
                }
                trace["error"] = attempt_trace["error"]
                continue
            if not isinstance(parsed, dict):
                attempt_trace["error"] = {
                    "type": "invalid_json",
                    "message": invalid_error,
                }
                trace["error"] = attempt_trace["error"]
                continue
            payload = parsed
            attempt_trace["parse_mode"] = "strict_json"
            trace["error"] = None
            break

        trace["finished_at"] = _utc_now()
        trace["duration_ms"] = round(
            (time.perf_counter() - started_clock) * 1000,
            3,
        )
        if payload is None:
            if trace.get("error", {}).get("type") == "empty_response":
                raise DeepSeekCallError(empty_error, trace=trace)
            error = DeepSeekCallError(invalid_error, trace=trace)
            if last_parse_error is not None:
                raise error from last_parse_error
            raise error

        trace["parsed_payload"] = payload
        return {
            "payload": payload,
            "usage": trace["usage"],
            "trace": trace,
        }
