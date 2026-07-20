# Third-party notices

This package downloads and builds QuantConnect LEAN from its public repository during Docker build. LEAN is licensed under Apache License 2.0. Review the upstream repository and license before redistribution.

The Docker image also installs Microsoft .NET Runtime/SDK, Python, Miniconda, NumPy, pandas, SciPy, scikit-learn, XGBoost, LightGBM, joblib, requests, FastAPI and related dependencies. Their respective licenses apply.

## Market data

No real third-party market data is included in this package.

The optional data synchronization tool connects to the Tiingo End-of-Day Prices API using a token supplied by the user. Tiingo data, API access, account type, internal-use restrictions and redistribution rights remain governed by Tiingo's current terms and the user's subscription agreement.

This package follows a bring-your-own-token model. Do not redistribute downloaded data unless you have the required permission or redistribution license.

The package can still contain an optional deterministic synthetic smoke-data generator, but production configuration disables it by default. Synthetic data must never be presented as real market data or used for investment-performance claims.
