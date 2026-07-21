from __future__ import annotations

import hashlib

from alphaforge.codegen.template_renderer import QCTemplateRenderer, build_code_region
from alphaforge.schemas.agent_outputs import GeneratedCode, StrategyCompilationRequest
from alphaforge.schemas.strategy_spec import HybridLogic, MLLogic, StrategySpec, TraditionalLogic


class DeterministicStrategyCompiler:
    """Compile a validated StrategySpec without model-generated source code."""

    VERSION = "deterministic_strategy_compiler_v1"

    def __init__(self, renderer: QCTemplateRenderer | None = None) -> None:
        self.renderer = renderer or QCTemplateRenderer()

    def compile(self, request: StrategyCompilationRequest) -> GeneratedCode:
        spec = request.strategy_spec
        expected_version = self.renderer.template_version(spec.candidate_type)
        expected_template_sha = self.renderer.template_sha256(spec.candidate_type)
        failures = [
            code
            for failed, code in (
                (request.template_version != expected_version, "TEMPLATE_VERSION_MISMATCH"),
                (request.template_sha256 != expected_template_sha, "TEMPLATE_DIGEST_MISMATCH"),
                (
                    request.semantics_version != self.renderer.SEMANTICS_VERSION,
                    "SEMANTICS_VERSION_MISMATCH",
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
            assumptions=("daily adjusted equity data are available",),
            compiler_metadata={
                "component": "deterministic_strategy_compiler",
                "output_mode": "validated_template_regions",
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
        expected = self.renderer.REQUIRED_REGIONS[spec.candidate_type]
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
        return build_code_region(
            "compute_traditional_scores",
            f'''def compute_traditional_scores(self):
    history = self.History(list(self.symbols.values()), {logic.lookback_days + 1}, Resolution.Daily)
    if history.empty or "close" not in history.columns:
        return {{}}
    closes = history["close"].unstack(level="symbol").sort_index()
    scores = {{}}
    for symbol in self.symbols.values():
        if symbol not in closes.columns:
            continue
        series = closes[symbol].dropna()
        if len(series) < {logic.lookback_days + 1}:
            continue
        first_price = float(series.iloc[-{logic.lookback_days + 1}])
        last_price = float(series.iloc[-1])
        if not np.isfinite(first_price) or not np.isfinite(last_price) or first_price == 0.0:
            continue
        scores[symbol] = {direction} * (last_price / first_price - 1.0)
    return scores''',
        )

    def _ml_regions(self, logic: MLLogic):
        estimator = self._estimator(logic)
        label_expression = (
            "future_returns.sub(future_returns.mean(axis=1), axis=0)"
            if logic.task == "relative_alpha_regression"
            else "(future_returns > 0.0).astype(float)"
        )
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
        return (
            build_code_region(
                "build_features",
                f'''def build_features(self):
    columns = [{feature_columns}]
    history = self.History(list(self.symbols.values()), 127, Resolution.Daily)
    if history.empty or "close" not in history.columns or "volume" not in history.columns:
        return pd.DataFrame(columns=columns)
    closes = history["close"].unstack(level="symbol").sort_index()
    volumes = history["volume"].unstack(level="symbol").sort_index()
    rows = {{}}
    for symbol in self.symbols.values():
        if symbol not in closes.columns or symbol not in volumes.columns:
            continue
        frame = pd.concat([closes[symbol].rename("close"), volumes[symbol].rename("volume")], axis=1).dropna()
        if len(frame) < 127:
            continue
        price = frame["close"]
        volume = frame["volume"]
        daily_returns = price.pct_change().dropna()
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
    history = self.History(list(self.symbols.values()), {history_bars}, Resolution.Daily)
    if history.empty or "close" not in history.columns or "volume" not in history.columns:
        return pd.DataFrame(columns=columns), pd.Series(dtype=float)
    closes = history["close"].unstack(level="symbol").sort_index()
    volumes = history["volume"].unstack(level="symbol").sort_index()
    daily_returns = closes.pct_change()
    feature_frames = {{
        "return_5d": closes.pct_change(5),
        "return_21d": closes.pct_change(21),
        "return_63d": closes.pct_change(63),
        "return_126d": closes.pct_change(126),
        "volatility_21d": daily_returns.rolling(21).std() * np.sqrt(252.0),
        "volatility_63d": daily_returns.rolling(63).std() * np.sqrt(252.0),
        "volume_ratio_21d": volumes / volumes.rolling(21).mean(),
        "volume_ratio_63d": volumes / volumes.rolling(63).mean(),
    }}
    features = pd.concat({{name: frame.stack() for name, frame in feature_frames.items()}}, axis=1)
    future_returns = closes.shift(-{logic.prediction_horizon_days}) / closes - 1.0
    labels_frame = {label_expression}
    labels = labels_frame.stack().rename("label")
    dataset = features.join(labels).replace([np.inf, -np.inf], np.nan).dropna()
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
    return model''',
            ),
            build_code_region(
                "predict_scores",
                f'''def predict_scores(self, model, features):
    if model is None or features.empty or not np.isfinite(features.to_numpy()).all():
        return {{}}{prediction}
    return {{symbol: float(score) for symbol, score in zip(features.index, predictions) if np.isfinite(score)}}''',
            ),
        )

    def _hybrid_region(self, weight: float):
        return build_code_region(
            "combine_scores",
            f'''def combine_scores(self, traditional_scores, ml_scores):
    common = sorted(set(traditional_scores) & set(ml_scores), key=str)
    common = [symbol for symbol in common if np.isfinite(traditional_scores[symbol]) and np.isfinite(ml_scores[symbol])]
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
