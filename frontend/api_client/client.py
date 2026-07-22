from __future__ import annotations

import os
from typing import Any

import requests


class AlphaForgeAPIError(RuntimeError):
    pass


class AlphaForgeAPI:
    """Single integration boundary between Streamlit and FastAPI."""

    def __init__(self) -> None:
        self.base_url = os.getenv("ALPHAFORGE_API_BASE_URL", "http://backend:8000/v1").rstrip("/")
        self.mock_mode = os.getenv("ALPHAFORGE_MOCK_MODE", "false").lower() == "true"

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = requests.request(method, f"{self.base_url}{path}", timeout=20, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            detail = ""
            if getattr(exc, "response", None) is not None:
                detail = f": {exc.response.text[:500]}"
            raise AlphaForgeAPIError(f"Backend request failed{detail}") from exc

    def health(self) -> dict[str, Any]:
        if self.mock_mode:
            return {"mode": "mock", "frontend": "healthy", "backend": "reserved", "lean_worker": "reserved"}
        return self._request("GET", "/health")

    def create_battle(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.mock_mode:
            return {
                "battle_id": "demo-battle",
                "status": "contract_locked",
                "contract_hash": "demo-contract-hash",
                "created_at": "demo",
                **payload,
            }
        return self._request("POST", "/battles", json=payload)

    def universe(self) -> dict[str, Any]:
        if self.mock_mode:
            tickers = [
                "MSFT", "AAPL", "NVDA", "GOOGL", "AMZN", "META", "AVGO", "ASML", "AMD", "ORCL",
                "JPM", "BRK.B", "V", "LLY", "JNJ", "ABBV", "TMO", "WMT", "COST", "PG",
                "KO", "MCD", "CAT", "HON", "UNP", "ETN", "XOM", "LIN", "NEE", "PLD",
            ]
            return {
                "universe_id": "alphaforge_us_equity_30_v1.0",
                "minimum_selectable": 5,
                "maximum_selectable": 30,
                "default_symbols": tickers,
                "tradable_symbols": [
                    {"display_ticker": ticker, "sector": "Demo"} for ticker in tickers
                ],
            }
        return self._request("GET", "/catalog/universe")

    def guided_strategies(self) -> list[dict[str, Any]]:
        if self.mock_mode:
            return [
                {
                    "template_id": "multi_horizon_momentum",
                    "display_name": "Multi-Horizon Momentum",
                    "default_lookback_days": 126,
                    "description": "Blend short, medium and long momentum with stock and market trend confirmation.",
                    "best_for": "Designed to reduce single-lookback fragility; improvement is not guaranteed.",
                },
                {
                    "template_id": "risk_adjusted_momentum",
                    "display_name": "Risk-Adjusted Momentum",
                    "default_lookback_days": 126,
                    "description": "Rank blended momentum per unit of realized volatility with trend gates.",
                    "best_for": "Designed to avoid rewarding volatile momentum blindly; improvement is not guaranteed.",
                },
                {
                    "template_id": "low_volatility",
                    "display_name": "Low Volatility",
                    "default_lookback_days": 63,
                    "description": "Rank stocks by realized volatility and hold the calmest names under the shared risk gate.",
                    "best_for": "Defensive positioning; may lag during sharp risk-on rallies.",
                },
            ]
        return self._request("GET", "/catalog/guided-strategies")

    def run_baselines(self, battle_id: str) -> dict[str, Any]:
        if self.mock_mode:
            return {"batch_id": "demo-baselines", "battle_id": battle_id, "state": "completed"}
        return self._request("POST", f"/battles/{battle_id}/baselines/run")

    def baselines(self, battle_id: str, refresh: bool = True) -> dict[str, Any] | None:
        if self.mock_mode:
            return None
        value = "true" if refresh else "false"
        return self._request("GET", f"/battles/{battle_id}/baselines?refresh={value}")

    def validate_code(self, battle_id: str, code: str) -> dict[str, Any]:
        if self.mock_mode:
            checks = {
                "Python syntax": "class" in code and "def initialize_strategy" in code,
                "UserStrategy entry": "class UserStrategy" in code,
                "AlphaForge base contract": "AlphaForgeBaseAlgorithm" in code,
                "Restricted imports": "subprocess" not in code and "socket" not in code,
            }
            return {
                "battle_id": battle_id,
                "code_hash": "mock-code-hash",
                "accepted": all(checks.values()),
                "checks": checks,
                "errors": [],
                "smoke_status": "completed",
                "smoke_run_id": "mock-smoke-run",
            }
        return self._request("POST", "/strategies/code/validate", json={"battle_id": battle_id, "code": code})

    def code_validation(self, battle_id: str) -> dict[str, Any]:
        if self.mock_mode:
            return self.validate_code(battle_id, "class UserStrategy AlphaForgeBaseAlgorithm def initialize_strategy")
        return self._request("GET", f"/strategies/code/validate/{battle_id}")

    def endpoint_registry(self) -> list[tuple[str, str]]:
        return [
            ("POST", "/battles"),
            ("POST", "/strategies/guided/preview"),
            ("GET", "/catalog/guided-strategies"),
            ("POST", "/strategies/code/validate"),
            ("GET", "/strategies/code/validate/{battle_id}"),
            ("POST", "/battles/{id}/baselines/run"),
            ("GET", "/battles/{id}/baselines"),
            ("POST", "/battles/{id}/rounds/{round}/ai-forge"),
            ("GET", "/battles/{id}/rounds/{round}/agent-events"),
            ("POST", "/battles/{id}/rounds/{round}/evaluate"),
            ("GET", "/battles/{id}/rounds/{round}/education-summary"),
            ("POST", "/battles/{id}/rounds/{round}/next"),
        ]

