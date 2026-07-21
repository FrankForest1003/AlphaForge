# price_volume_v1 model interface

Version: ml_feature_interface_v1
Applies to: ML and Hybrid routes under qc_semantics_v1

## Canonical feature columns

The feature order and spelling are fixed for both training and prediction:

```python
FEATURE_COLUMNS = (
    "return_5d",
    "return_21d",
    "return_63d",
    "return_126d",
    "volatility_21d",
    "volatility_63d",
    "volume_ratio_21_63",
)
```

`build_features` returns a DataFrame indexed by Symbol with exactly these columns in this order. It
contains only finite rows. The DataFrame index must be built from the same Symbols whose feature rows
were appended; do not derive the index from a broader candidate list after filtering.

`build_training_set` returns `(X, y)`. X is a DataFrame with MultiIndex `(time, symbol)` and exactly
the same `FEATURE_COLUMNS`. y is a finite Series named `label` with exactly the same index as X.

`fit_model` must reject an empty X/y pair. It fits the estimator with the StrategySpec random seed.
`predict_scores` must reject an empty or non-finite prediction DataFrame and pass the same ordered
feature columns used during fitting. A valid pattern is:

```python
X = X.loc[:, FEATURE_COLUMNS]
prediction_X = features.loc[:, FEATURE_COLUMNS]
model.fit(X, y)
predictions = model.predict(prediction_X)
```

## Training dates and labels

- `training_window_days` counts unique trading dates, not stacked Symbol rows and not calendar days.
- Select the most recent configured number of unique dates after removing rows without a fully
  observed forward label.
- A training feature row at date t may use data available through t only.
- Its label may use the realized close at t + prediction_horizon_days because t is a historical row.
- The current prediction row has no forward label and must never be included in X or y.
- Relative-alpha regression label is the Symbol forward return minus the mean forward return across
  all valid Symbols at the same t.
- Never fill missing feature or label values with zero.

## Hybrid fusion

Traditional and ML scores must be restricted to their common valid Symbol set. Convert each score
vector independently to cross-sectional percentile ranks, then combine with the StrategySpec weight.
If either score vector is empty or fewer than two common Symbols remain, return no score and let the
deterministic no-score portfolio policy execute.
