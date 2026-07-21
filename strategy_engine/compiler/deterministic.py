from __future__ import annotations

import hashlib

from alphaforge.schemas.agent_outputs import GeneratedCode, StrategyCompilationRequest
from alphaforge.schemas.strategy_spec import HybridLogic, MLLogic, StrategySpec, TraditionalLogic
from strategy_engine.compiler.renderer import QCTemplateRenderer, build_code_region


class DeterministicStrategyCompiler:
    """Compile a validated StrategySpec for AlphaForge Local LEAN Runtime."""

    VERSION = "deterministic_strategy_compiler_v2"

    def __init__(self, renderer: QCTemplateRenderer | None = None) -> None:
        self.renderer = renderer or QCTemplateRenderer()

    def compile(self, request: StrategyCompilationRequest) -> GeneratedCode:
        spec = request.strategy_spec
        route = spec.logic.kind
        expected_version = self.renderer.template_version(route)
        expected_template_sha = self.renderer.template_sha256(route)
        failures = [
            code
            for failed, code in (
                (request.template_version != expected_version, "TEMPLATE_VERSION_MISMATCH"),
                (request.template_sha256 != expected_template_sha, "TEMPLATE_DIGEST_MISMATCH"),
                (
                    request.semantics_version != self.renderer.SEMANTICS_VERSION,
                    "SEMANTICS_VERSION_MISMATCH",
                ),
                (
                    expected_version not in request.lean_environment.template_compatibility,
                    "TEMPLATE_NOT_SUPPORTED_BY_ENVIRONMENT",
                ),
                (
                    request.lean_environment.normalization_mode != "raw",
                    "LOCAL_LEAN_REQUIRES_RAW_NORMALIZATION",
                ),
            )
            if failed
        ]
        if failures:
            raise ValueError(",".join(failures))

        regions = self._regions(spec)
        rendered = self.renderer.render(spec, regions)
        compiler_sha = hashlib.sha256(
            f"{self.VERSION}\n{rendered.template_sha256}".encode("utf-8")
        ).hexdigest()
        return GeneratedCode(
            strategy_id=spec.strategy_id,
            source=rendered.source,
            source_sha256=rendered.source_sha256,
            spec_sha256=request.spec_sha256,
            used_qc_api=self.renderer.BASE_QC_API,
            assumptions=(
                "RAW daily US-equity data are provided by AlphaForge Local LEAN Runtime",
                "alphaforge_base.py is mounted by the Worker",
            ),
            compiler_metadata={
                "component": "strategy_engine.compiler",
                "output_mode": "validated_local_lean_template",
                "runtime_contract": "local_lean_v1.1.3",
                "algorithm_class": self.renderer.algorithm_class(spec.strategy_id),
                "completion_marker": self.renderer.completion_marker(spec.strategy_id),
            },
            template_version=rendered.template_version,
            template_sha256=rendered.template_sha256,
            compiler_version=self.VERSION,
            compiler_sha256=compiler_sha,
            semantics_version=request.semantics_version,
            regions=regions,
        )

    def _regions(self, spec: StrategySpec):
        regions = []
        traditional = self._traditional_logic(spec)
        ml = self._ml_logic(spec)
        if traditional is not None:
            regions.append(self._traditional_region(traditional))
        if ml is not None:
            regions.extend(self._ml_regions(ml))
        if isinstance(spec.logic, HybridLogic):
            regions.append(self._hybrid_region(spec.logic.traditional_weight))
        expected = self.renderer.REQUIRED_REGIONS[spec.logic.kind]
        by_name = {region.name: region for region in regions}
        return tuple(by_name[name] for name in expected)

    def _traditional_logic(self, spec: StrategySpec) -> TraditionalLogic | None:
        if isinstance(spec.logic, TraditionalLogic):
            return spec.logic
        if isinstance(spec.logic, HybridLogic):
            return spec.logic.traditional
        return None

    def _ml_logic(self, spec: StrategySpec) -> MLLogic | None:
        if isinstance(spec.logic, MLLogic):
            return spec.logic
        if isinstance(spec.logic, HybridLogic):
            return spec.logic.ml
        return None

    def _traditional_region(self, logic: TraditionalLogic):
        direction = "1.0" if logic.signal == "momentum_rank" else "-1.0"
        bars = logic.lookback_days + 1
        return build_code_region(
            "compute_traditional_scores",
            f'''def compute_traditional_scores(self):
    history = self.history(self.symbols, {bars}, Resolution.DAILY)
    frames = af_split_history_frames(history)
    scores = {{}}
    for symbol in self.symbols:
        frame = frames.get(symbol.value.upper())
        if frame is None or frame.empty or "close" not in frame.columns:
            continue
        window = frame["close"].astype(float).iloc[-{bars}:]
        if len(window) != {bars} or window.isna().any():
            continue
        first_price = float(window.iloc[0])
        last_price = float(window.iloc[-1])
        if not np.isfinite(first_price) or not np.isfinite(last_price) or first_price <= 0.0:
            continue
        scores[symbol] = {direction} * (last_price / first_price - 1.0)
    return scores''',
        )

    def _ml_regions(self, logic: MLLogic):
        estimator = self._estimator(logic)
        classifier_guard = (
            "\n    if labels.nunique() < 2:\n        return None"
            if logic.task == "direction_classification"
            else ""
        )
        prediction = (
            '''
    if not hasattr(model, "predict_proba") or 1 not in model.classes_:
        return {}
    class_index = list(model.classes_).index(1)
    predictions = model.predict_proba(features)[:, class_index]'''
            if logic.task == "direction_classification"
            else "\n    predictions = model.predict(features)"
        )
        history_bars = logic.training_window_days + 126 + logic.prediction_horizon_days
        feature_columns = (
            '"return_5d", "return_21d", "return_63d", "return_126d", '
            '"volatility_21d", "volatility_63d", "volume_ratio_21d", "volume_ratio_63d"'
        )
        label_block = (
            '''dataset["label"] = dataset["raw_label"] - dataset.groupby(
        level="time"
    )["raw_label"].transform("mean")'''
            if logic.task == "relative_alpha_regression"
            else '''dataset["label"] = dataset["raw_label"].where(
        dataset["raw_label"].isna(),
        (dataset["raw_label"] > 0.0).astype(float),
    )'''
        )
        return (
            build_code_region(
                "build_features",
                f'''def build_features(self):
    columns = [{feature_columns}]
    history = self.history(self.symbols, 127, Resolution.DAILY)
    frames = af_split_history_frames(history)
    rows = {{}}
    for symbol in self.symbols:
        frame = frames.get(symbol.value.upper())
        if frame is None or frame.empty or "close" not in frame.columns or "volume" not in frame.columns:
            continue
        window = frame[["close", "volume"]].astype(float).iloc[-127:]
        if len(window) != 127 or window.isna().any().any():
            continue
        price = window["close"]
        volume = window["volume"]
        daily_returns = price.pct_change()
        values = [
            price.iloc[-1] / price.iloc[-6] - 1.0,
            price.iloc[-1] / price.iloc[-22] - 1.0,
            price.iloc[-1] / price.iloc[-64] - 1.0,
            price.iloc[-1] / price.iloc[-127] - 1.0,
            daily_returns.iloc[-21:].std() * np.sqrt(252.0),
            daily_returns.iloc[-63:].std() * np.sqrt(252.0),
            volume.iloc[-1] / volume.iloc[-21:].mean(),
            volume.iloc[-1] / volume.iloc[-63:].mean(),
        ]
        if all(np.isfinite(value) for value in values):
            rows[symbol] = values
    return pd.DataFrame.from_dict(rows, orient="index", columns=columns)''',
            ),
            build_code_region(
                "build_training_set",
                f'''def build_training_set(self):
    columns = [{feature_columns}]
    history = self.history(self.symbols, {history_bars}, Resolution.DAILY)
    frames = af_split_history_frames(history)
    parts = []
    for symbol in self.symbols:
        frame = frames.get(symbol.value.upper())
        if frame is None or frame.empty or "close" not in frame.columns or "volume" not in frame.columns:
            continue
        close = frame["close"].astype(float)
        volume = frame["volume"].astype(float)
        daily_returns = close.pct_change()
        features = pd.DataFrame(index=frame.index)
        features["return_5d"] = close.pct_change(5)
        features["return_21d"] = close.pct_change(21)
        features["return_63d"] = close.pct_change(63)
        features["return_126d"] = close.pct_change(126)
        features["volatility_21d"] = daily_returns.rolling(21).std() * np.sqrt(252.0)
        features["volatility_63d"] = daily_returns.rolling(63).std() * np.sqrt(252.0)
        features["volume_ratio_21d"] = volume / volume.rolling(21).mean()
        features["volume_ratio_63d"] = volume / volume.rolling(63).mean()
        features["raw_label"] = close.shift(-{logic.prediction_horizon_days}) / close - 1.0
        features["symbol"] = symbol
        features.index.name = "time"
        parts.append(features.reset_index().set_index(["time", "symbol"]))
    if not parts:
        return pd.DataFrame(columns=columns), pd.Series(dtype=float)
    dataset = pd.concat(parts).replace([np.inf, -np.inf], np.nan)
    {label_block}
    dataset = dataset.dropna(subset=[*columns, "label"])
    if dataset.empty:
        return pd.DataFrame(columns=columns), pd.Series(dtype=float)
    dates = dataset.index.get_level_values("time").unique().sort_values()
    dates = dates[-{logic.training_window_days}:]
    dataset = dataset[dataset.index.get_level_values("time").isin(dates)]
    return dataset[columns].astype(float), dataset["label"].astype(float)''',
            ),
            build_code_region(
                "fit_model",
                f'''def fit_model(self, training_set):
    features, labels = training_set
    if features.empty or labels.empty:
        return None
    if not np.isfinite(features.to_numpy()).all() or not np.isfinite(labels.to_numpy()).all():
        return None{classifier_guard}
    model = {estimator}(random_state={logic.random_seed})
    model.fit(features, labels)
    importance = {{
        name: float(value)
        for name, value in zip(features.columns, getattr(model, "feature_importances_", []))
    }}
    self.af_record_ml_training({{
        "model_type": "{estimator}",
        "task": "{logic.task}",
        "sample_count": int(len(features)),
        "feature_names": [str(name) for name in features.columns],
        "feature_importance": importance,
        "training_window_days": {logic.training_window_days},
        "prediction_horizon_days": {logic.prediction_horizon_days},
        "random_seed": {logic.random_seed},
    }})
    return model''',
            ),
            build_code_region(
                "predict_scores",
                f'''def predict_scores(self, model, features):
    if model is None or features.empty or not np.isfinite(features.to_numpy()).all():
        return {{}}{prediction}
    scores = {{
        symbol: float(score)
        for symbol, score in zip(features.index, predictions)
        if np.isfinite(score)
    }}
    for rank, (symbol, score) in enumerate(
        sorted(scores.items(), key=lambda item: item[1], reverse=True), 1
    ):
        self.af_record_ml_prediction({{
            "symbol": symbol.value,
            "score": score,
            "rank": rank,
            "selected": rank <= self.top_k,
        }})
    return scores''',
            ),
        )

    def _hybrid_region(self, weight: float):
        return build_code_region(
            "combine_scores",
            f'''def combine_scores(self, traditional_scores, ml_scores):
    common = sorted(set(traditional_scores) & set(ml_scores), key=lambda symbol: symbol.value)
    common = [
        symbol
        for symbol in common
        if np.isfinite(traditional_scores[symbol]) and np.isfinite(ml_scores[symbol])
    ]
    if not common:
        return {{}}
    traditional = pd.Series({{symbol: traditional_scores[symbol] for symbol in common}}, dtype=float)
    machine_learning = pd.Series({{symbol: ml_scores[symbol] for symbol in common}}, dtype=float)
    traditional_percentile = traditional.rank(method="average", pct=True)
    ml_percentile = machine_learning.rank(method="average", pct=True)
    combined = {weight} * traditional_percentile + {1.0 - weight} * ml_percentile
    return combined.to_dict()''',
        )

    def _estimator(self, logic: MLLogic) -> str:
        suffix = "Regressor" if logic.task == "relative_alpha_regression" else "Classifier"
        prefix = "GradientBoosting" if logic.model == "gradient_boosting" else "RandomForest"
        return prefix + suffix
