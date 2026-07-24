# AlphaForge Architecture

## Purpose

AlphaForge is a local, education-first financial strategy laboratory. A frozen
experiment contract keeps the equity universe, dates, capital, benchmark, fees,
and slippage comparable across four public baselines, one Human strategy, and
three AI tracks.

## Stack

- React, Vite, and Recharts for workflow and result visualization;
- FastAPI and Pydantic for orchestration, APIs, and structured contracts;
- DeepSeek JSON API for a Parameter Designer and Performance Critic;
- QuantConnect LEAN as the sole backtest engine;
- pandas, NumPy, and scikit-learn inside a fixed strategy template;
- Docker Compose for the frontend, backend, and LEAN Worker.

## AI workflow

Each Traditional, ML, and Hybrid track follows the same bounded process:

1. Designer returns an explanation and a complete `StrategyTemplateSpec`.
2. Pydantic validates and normalizes the parameters.
3. The backend injects canonical JSON into the versioned `template-v1`.
4. LEAN executes the compiled strategy.
5. Critic evaluates metrics and execution evidence against public references.
6. Designer receives the critique and writes the next complete parameter set.
7. After at most three backtests, the backend keeps the highest Sharpe, then
   highest CAGR, then lower maximum-drawdown result.

The Critic provides diagnosis and at most three parameter directions. It cannot
write code, replace the parameter object, or issue accept/reject decisions.

## Executability boundary

Agents never generate Python. The fixed template owns LEAN APIs, history access,
feature construction, time-safe labels, model fitting, inference, portfolio
construction, risk controls, and runtime evidence. Any parameter object accepted
by `StrategyTemplateSpec` is expected to compile and run. A runtime failure from
a valid spec is a template or platform defect, not an Agent repair problem.

The compiler embeds canonical parameter JSON and its SHA-256 digest, making every
trial reproducible from its history record.

## Track integrity

- Traditional requires a transparent signal and forbids an ML model.
- ML requires a fitted model and forbids a separate transparent signal blend.
- Hybrid requires both and combines them in the same final decision.

The DSL supports bounded price/volume features, four sklearn model families,
Top-K selection, five portfolio weighting modes, weekly/monthly schedules, and
explicit risk controls. Shared experiment settings cannot be changed by Agents.

## Education and limitations

The UI shows all three trials, parameter changes, Critic feedback, returns,
drawdowns, turnover, costs, equity curves, and the retained trial. This turns the
optimization loop into an observable lesson about risk-return trade-offs.

Selecting the best of three still creates multiple-testing bias. The retained
trial is an in-sample development result, not evidence of future profit.
Robustness scenarios communicate sensitivity to periods, costs, and execution
assumptions.

## Information boundary

Designers and Critics receive public baselines, the frozen run contract, and
their own AI iteration history. Human source, parameters, results, orders, and
personalized education are excluded. Guided and custom Human code remain a
separate path.
