# AlphaForge Architecture

## Purpose

AlphaForge is a local, education-first financial strategy laboratory. A frozen
experiment contract keeps the equity universe, dates, capital, benchmark, fees,
and slippage comparable across four public baselines, one Human strategy, and
three AI tracks.

## Stack

- React, Vite, and Recharts for workflow and result visualization;
- FastAPI and Pydantic for orchestration, APIs, and structured contracts;
- DeepSeek JSON API for a Parameter Designer, Performance Critic, and asynchronous Teaching Explainer;
- a cross-round AI Coach for evidence-based refine, mechanism-rotation, or track-rebuild decisions;
- QuantConnect LEAN as the sole backtest engine;
- pandas, NumPy, and scikit-learn inside a fixed strategy template;
- SQLite for users, sessions, best-of-five battles, round evidence, and Coach memory;
- Docker Compose for the frontend, backend, and four isolated LEAN Worker slots.
- A sticky Worker Pool routes by current load. Market data is shared read-only, while launcher configuration, locks, jobs, models, and result directories remain isolated.

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
8. In a battle, that result challenges the track's cross-round incumbent. The
   prior champion remains active when the new trials do not beat it.
9. The AI Coach uses computed improvement and public-reference gaps to choose
   `refine_parameters`, `rotate_mechanism`, or `rebuild_track` for the next round.

The Critic provides diagnosis and at most three parameter directions. It cannot
write code, replace the parameter object, or issue accept/reject decisions.
The Coach cannot see Human evidence. Its decision includes a change scope and
parameter budget, and the assigned track directive is passed to the next Designer.

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

Current-round challenger trials and the retained champion lineage are stored
separately. If an earlier-round champion survives, Learning Review displays the
iterations that actually produced that champion rather than the losing current
challengers.

The deterministic Judge uses 35% Sharpe, 30% CAGR, 15% drawdown control, and 5%
each for volatility, cost, execution evidence, and explainability. The Teaching
Explainer runs after completion and may only translate frozen evidence into a
strategy explanation, one-variable next-round experiments, and a relevant quant
concept. Its failure never changes the winner or blocks the completed run.

Guided Human strategies offer basic presets and an advanced multi-factor form.
Both compile through the same validated fixed template; complete custom
QuantConnect Python remains available as a separate checked input.

## Battle lifecycle and persistence

A battle is best of five and ends when either side reaches three wins. Round 1
freezes the experiment contract and persists the complete four-baseline evidence;
Rounds 2–5 reuse that evidence instead of rerunning identical baselines. Users can
switch directly between R1–R5, apply evidence-based Human parameter suggestions,
review AI Coach decisions, reopen persisted runs after a backend restart, and
delete an entire battle. SQLite stores identity and battle state, while complete
Forge snapshots preserve curves, code, candidate evidence, and champion lineage.

Selecting the best of three still creates multiple-testing bias. The retained
trial is an in-sample development result, not evidence of future profit.
Robustness protocol v2 applies scenario-specific CAGR/Sharpe retention and
drawdown thresholds, weights regime, start-date, friction, and universe stresses,
and requires every planned run plus an acceptable worst-case scenario.

## Information boundary

Designers and Critics receive public baselines, the frozen run contract, and
their own AI iteration history. Human source, parameters, results, orders, and
personalized education are excluded. Guided and custom Human code remain a
separate path.
