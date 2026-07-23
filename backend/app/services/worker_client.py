from __future__ import annotations

from typing import Any

import requests


class WorkerClientError(RuntimeError):
    pass


class LeanWorkerClient:
    def __init__(self, base_url: str, token: str = "", timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {"X-Worker-Token": token} if token else {}

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        parse_json = kwargs.pop("parse_json", True)
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                headers=self.headers,
                timeout=self.timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response.json() if parse_json else response.text
        except requests.RequestException as exc:
            detail = ""
            if getattr(exc, "response", None) is not None:
                detail = f": {exc.response.text[:500]}"
            raise WorkerClientError(f"LEAN Worker request failed{detail}") from exc

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def submit(self, strategy_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/jobs",
            json={"strategy_id": strategy_id, "parameters": parameters},
        )

    def submit_custom(
        self,
        algorithm_code: str,
        parameters: dict[str, Any],
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "algorithm_code": algorithm_code,
            "parameters": parameters,
        }
        if timeout_seconds is not None:
            payload["timeout_seconds"] = timeout_seconds
        return self._request("POST", "/v1/custom-jobs", json=payload)

    def job(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/jobs/{run_id}")

    def result(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/jobs/{run_id}/result")

    def log(self, run_id: str) -> str:
        return self._request("GET", f"/v1/jobs/{run_id}/log", parse_json=False)

    def details(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/jobs/{run_id}/details")
