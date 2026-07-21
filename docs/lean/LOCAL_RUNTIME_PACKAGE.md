# Local LEAN Runtime Package

The validated package is stored under `lean_worker/`.

- Runtime version: `1.1.3`
- Fixed LEAN commit: see `lean_worker/PACKAGE_MANIFEST.json`
- Full setup: `lean_worker/README_zh.md`
- API guide: `lean_worker/docs/API_GUIDE_zh.md`
- Result schema: `lean_worker/docs/RESULT_SCHEMA.md`
- Data/license policy: `lean_worker/docs/DATA_SOURCE_AND_LICENSE_zh.md`
- Generated strategy contract: `lean_worker/docs/GENERATED_STRATEGY_CONTRACT.md`

The package contains no real market data or API token. The backend deploys generated candidates to `POST /v1/strategies/generated`, then submits Smoke and full-backtest jobs through the authenticated Worker API. Do not commit anything generated under the worker workspace except the existing `.gitkeep` files.
