#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from alphaforge.schemas.agent_outputs import OptimizationResult
from alphaforge.schemas.backtest import BacktestResult, BacktestSubmission
from alphaforge.schemas.manifests import LeanEnvironmentManifest, StrategyManifest
from alphaforge.schemas.optimisation import OptimizationRequest
from alphaforge.schemas.strategy_spec import StrategySpec


def main() -> None:
    output_dir = Path(__file__).resolve().parents[1] / "docs" / "api" / "schemas"
    output_dir.mkdir(parents=True, exist_ok=True)
    models = (
        StrategySpec,
        StrategyManifest,
        LeanEnvironmentManifest,
        BacktestSubmission,
        BacktestResult,
        OptimizationRequest,
        OptimizationResult,
    )
    for model in models:
        path = output_dir / f"{model.__name__}.schema.json"
        path.write_text(
            json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
