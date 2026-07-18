from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from alphaforge.config import ModelSettings

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(RuntimeError):
    pass


class StructuredModelClient:
    """Strict JSON client with one validation-directed correction attempt."""

    def __init__(self, settings: ModelSettings, *, timeout_seconds: int = 120) -> None:
        self.settings = settings
        self.endpoint = settings.base_url.rstrip("/") + "/chat/completions"
        self.timeout_seconds = timeout_seconds

    def complete(
        self,
        *,
        output_model: type[T],
        system_prompt: str,
        payload: dict[str, Any],
    ) -> T:
        validation_feedback: str | None = None
        last_error: Exception | None = None
        for attempt in (1, 2):
            request_payload = dict(payload)
            if validation_feedback is not None:
                request_payload["validation_feedback"] = validation_feedback
                request_payload["instruction"] = (
                    "Return a corrected JSON object matching the supplied schema exactly."
                )
            content = self._request(
                system_prompt=system_prompt,
                payload=request_payload,
                schema=output_model.model_json_schema(),
            )
            try:
                raw = json.loads(content)
                if not isinstance(raw, dict):
                    raise ValueError("response must be a JSON object")
                return output_model.model_validate(raw)
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                last_error = exc
                validation_feedback = str(exc)
                if attempt == 2:
                    break
        raise StructuredOutputError(
            f"structured output failed after one correction attempt: {last_error}"
        )

    def _request(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
    ) -> str:
        body = {
            "model": self.settings.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                    + " Return one JSON object only. Unknown fields are forbidden.",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"json_schema": schema, "input": payload},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            "max_tokens": 5000,
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                envelope = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise StructuredOutputError(f"model HTTP request failed with status {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise StructuredOutputError(f"model request failed: {exc.reason}") from exc
        try:
            return envelope["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise StructuredOutputError("model response envelope is invalid") from exc
