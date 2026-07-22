# AlphaForge Platform Backend

This FastAPI service owns immutable `ExperimentContract` records and orchestrates
the four public baselines through the isolated LEAN Worker. It does not execute
strategy code itself.

## Local run

```powershell
python -m pip install -r backend/requirements.txt
$env:ALPHAFORGE_WORKER_URL = "http://127.0.0.1:18081"
python -m uvicorn app.main:app --app-dir backend --port 8000
```

The minimum selectable universe is five stocks. All four baseline jobs receive
the same symbol list, dates, capital, fees, slippage, risk limits, data version,
random seed, and experiment-contract hash.

AI Forge intentionally returns `501 agent_runtime_not_configured` until the
member-D runtime is connected.
