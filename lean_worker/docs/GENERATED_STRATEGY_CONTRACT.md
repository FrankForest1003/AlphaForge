# Generated Strategy Runtime Contract

Generated candidate source is produced only by the deterministic `strategy_engine` compiler. The Local LEAN Worker does not invoke a model to write or patch source.

Every deployed candidate must:

- inherit `AlphaForgeBaseAlgorithm`;
- target LEAN 2.5 and Python 3.11 on linux/amd64;
- use US Equity Daily subscriptions with `DataNormalizationMode.RAW`;
- remain long-only with leverage 1, target gross at most 0.95, position weight at most 0.35 and free portfolio value at least 0.02;
- use `af_rebalance_to_weights` for staged sell/reduce-before-buy execution;
- isolate missing or incomplete Symbol history without forward-filling pre-listing data;
- use walk-forward ML with fully realized labels and a fixed seed;
- emit JSON-native signals, training metadata and predictions through the base recorder;
- emit the registered completion marker from `on_alpha_end`;
- avoid network, subprocess, package installation, unrestricted file access and unavailable dependencies.

Deployment is accepted only when source SHA-256 and StrategySpec SHA-256 match the submitted manifest and all static validators pass.
