from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import threading
from typing import Any, Literal, TypeVar

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from pydantic import BaseModel, ValidationError

from alphaforge.config import ModelSettings
from alphaforge.agents.context import AgentContextBundle

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(RuntimeError):
    pass


class EmptyModelOutputError(StructuredOutputError):
    pass


@dataclass(frozen=True)
class CompletionPolicy:
    reasoning_effort: Literal["high", "max"]
    max_output_tokens: int

    def __post_init__(self) -> None:
        if self.reasoning_effort not in {"high", "max"}:
            raise ValueError("reasoning_effort must be a native value: high or max")
        if self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")


class StructuredModelClient:
    """Strict JSON client with one validation-directed correction attempt."""

    def __init__(
        self,
        settings: ModelSettings,
        *,
        timeout_seconds: int = 120,
        client: OpenAI | None = None,
        trace_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.settings = settings
        self.timeout_seconds = timeout_seconds
        self.trace_sink = trace_sink
        self.client = client or OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url.rstrip("/"),
            timeout=timeout_seconds,
            max_retries=0,
        )
        self._call_lock = threading.Lock()
        self._call_sequence = 0
        self._thread_state = threading.local()

    def complete(
        self,
        *,
        output_model: type[T],
        payload: dict[str, Any],
        context_bundle: AgentContextBundle,
        operation: str = "structured_completion",
        policy: CompletionPolicy = CompletionPolicy("high", 6000),
        result_validator: Callable[[T], None] | None = None,
    ) -> T:
        validation_feedback: str | None = None
        last_error: Exception | None = None
        for attempt in (1, 2):
            request_payload = dict(payload)
            if validation_feedback is not None:
                request_payload["validation_feedback"] = validation_feedback
            try:
                content = self._request(
                    payload=request_payload,
                    schema=output_model.model_json_schema(),
                    operation=operation,
                    attempt=attempt,
                    policy=policy,
                    context_bundle=context_bundle,
                )
            except EmptyModelOutputError as exc:
                last_error = exc
                validation_feedback = (
                    "The previous response used its output budget without producing final JSON. "
                    "Return a concise final JSON object now. " + str(exc)
                )
                self._trace(
                    "llm_validation",
                    operation=operation,
                    attempt=attempt,
                    output_model=output_model.__name__,
                    outcome="failed",
                    error=validation_feedback,
                    call_id=self._current_call_id(),
                )
                if attempt == 2:
                    break
                continue
            except Exception as exc:
                self._trace(
                    "llm_error",
                    operation=operation,
                    attempt=attempt,
                    error=f"{type(exc).__name__}: {exc}",
                    call_id=self._current_call_id(),
                )
                raise
            try:
                raw = json.loads(content)
                if not isinstance(raw, dict):
                    raise ValueError("response must be a JSON object")
                result = output_model.model_validate(raw)
                if result_validator is not None:
                    result_validator(result)
                self._trace(
                    "llm_validation",
                    operation=operation,
                    attempt=attempt,
                    output_model=output_model.__name__,
                    outcome="passed",
                    call_id=self._current_call_id(),
                )
                return result
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                last_error = exc
                validation_feedback = str(exc)
                self._trace(
                    "llm_validation",
                    operation=operation,
                    attempt=attempt,
                    output_model=output_model.__name__,
                    outcome="failed",
                    error=validation_feedback,
                    call_id=self._current_call_id(),
                )
                if attempt == 2:
                    break
        raise StructuredOutputError(
            f"structured output failed after one correction attempt: {last_error}"
        )

    def _request(
        self,
        *,
        payload: dict[str, Any],
        schema: dict[str, Any],
        context_bundle: AgentContextBundle,
        operation: str = "structured_completion",
        attempt: int = 1,
        policy: CompletionPolicy = CompletionPolicy("high", 6000),
    ) -> str:
        call_id = self._next_call_id()
        self._thread_state.call_id = call_id
        system_message = context_bundle.render()
        messages = [
            {
                "role": "system",
                "content": system_message,
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"json_schema": schema, "input": payload},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        ]
        request_kwargs: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "max_tokens": policy.max_output_tokens,
        }
        if self.settings.thinking_enabled:
            request_kwargs["reasoning_effort"] = policy.reasoning_effort
            request_kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        else:
            request_kwargs["temperature"] = 0.0
            request_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        self._trace(
            "llm_request",
            operation=operation,
            attempt=attempt,
            endpoint=self.settings.base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": "Bearer <redacted>", "Content-Type": "application/json"},
            body=request_kwargs,
            input=payload,
            json_schema=schema,
            system_prompt=system_message,
            context_bundle={
                "bundle_id": context_bundle.bundle_id,
                "bundle_version": context_bundle.bundle_version,
                "bundle_sha256": context_bundle.bundle_sha256,
                "prompt_id": context_bundle.prompt_id,
                "prompt_version": context_bundle.sections[0].source_version,
                "prompt_sha256": context_bundle.sections[0].source_sha256,
                "agent_role": context_bundle.agent_role,
                "candidate_type": context_bundle.candidate_type,
                "template_version": context_bundle.template_version,
                "character_count": context_bundle.character_count,
                "source_paths": context_bundle.source_paths,
            },
            call_id=call_id,
        )
        try:
            completion = self.client.chat.completions.create(**request_kwargs)
        except APIStatusError as exc:
            raise StructuredOutputError(
                f"model HTTP request failed with status {exc.status_code}"
            ) from exc
        except APITimeoutError as exc:
            raise StructuredOutputError("model request timed out") from exc
        except APIConnectionError as exc:
            raise StructuredOutputError("model connection failed") from exc

        if not completion.choices:
            raise StructuredOutputError("model response contains no choices")
        choice = completion.choices[0]
        content = choice.message.content or ""
        self._trace(
            "llm_response",
            operation=operation,
            attempt=attempt,
            content=content,
            usage=self._usage_dict(getattr(completion, "usage", None)),
            finish_reason=getattr(choice, "finish_reason", None),
            call_id=call_id,
        )
        if not content:
            raise EmptyModelOutputError(
                f"model response content is empty; finish_reason={getattr(choice, 'finish_reason', None)}"
            )
        return content

    def _next_call_id(self) -> int:
        with self._call_lock:
            self._call_sequence += 1
            return self._call_sequence

    def _current_call_id(self) -> int | None:
        return getattr(self._thread_state, "call_id", None)

    def _usage_dict(self, usage: Any) -> dict[str, Any]:
        if usage is None:
            return {}
        if hasattr(usage, "model_dump"):
            raw = usage.model_dump()
        elif isinstance(usage, dict):
            raw = dict(usage)
        else:
            raw = {
                name: getattr(usage, name)
                for name in (
                    "prompt_tokens",
                    "completion_tokens",
                    "total_tokens",
                    "prompt_cache_hit_tokens",
                    "prompt_cache_miss_tokens",
                )
                if hasattr(usage, name)
            }
        return {
            key: raw[key]
            for key in (
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "prompt_cache_hit_tokens",
                "prompt_cache_miss_tokens",
            )
            if key in raw and raw[key] is not None
        }

    def _trace(self, kind: str, **fields: Any) -> None:
        if self.trace_sink is None:
            return
        self.trace_sink(
            {
                "kind": kind,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                **fields,
            }
        )
