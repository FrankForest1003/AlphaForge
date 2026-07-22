# AlphaForge Platform Backend

This FastAPI service owns immutable `ExperimentContract` and Human strategy records,
then orchestrates one real Human run plus the four public baselines through the
isolated LEAN Worker. It does not execute strategy code itself.

## Local run

```powershell
python -m pip install -r backend/requirements.txt
$env:ALPHAFORGE_WORKER_URL = "http://127.0.0.1:18081"
python -m uvicorn app.main:app --app-dir backend --port 8000
```

The minimum selectable universe is five stocks. The Human job and all four baseline
jobs receive the same symbol list, dates, capital, fees, slippage, risk limits,
data version, random seed, and experiment-contract hash. Human rows are explicitly
tagged with `role=human` so a future Agent evidence bundle can exclude them.

Guided templates compile to approved Worker registry entries that do not reuse a
public-baseline strategy ID. Custom LEAN Python is stored as an immutable SHA-256
version, checked with a restricted AST contract, and must complete an isolated
Worker smoke run before the full Human-plus-four-baseline batch can start.

AI Forge intentionally returns `501 agent_runtime_not_configured` until the
member-D runtime is connected.
