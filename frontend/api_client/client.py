from __future__ import annotations

import os
from typing import Any

import requests


class AlphaForgeAPIError(RuntimeError):
    pass


class AlphaForgeAPI:
    def __init__(self) -> None:
        self.base_url = os.getenv(
            "ALPHAFORGE_API_BASE_URL", "http://backend:8000/v1"
        ).rstrip("/")

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                timeout=30,
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            detail = ""
            if getattr(exc, "response", None) is not None:
                detail = f": {exc.response.text[:500]}"
            raise AlphaForgeAPIError(f"Backend request failed{detail}") from exc

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def universe(self) -> dict[str, Any]:
        return self._request("GET", "/catalog/universe")

    def create_forge_run(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/forge-runs", json=request)

    def forge_run(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/forge-runs/{run_id}")
