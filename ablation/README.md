# AlphaForge Ablation Runner

`ablation` is a standalone experiment layer. It imports the existing Designer,
Critic, strategy compiler, and LEAN Worker clients; it does not add experiment
branches to the production Backend or Frontend.

## Studies

- `studies/reliability.json` measures Designer structured-output reliability
  without LEAN. Its arms test the current configuration, thinking disabled, the
  valid output example removed, and a single API/schema attempt.
- `studies/forge_core.json` compares the full three-iteration loop with Critic
  removed and baseline context removed. It freezes four completed public
  baselines from one existing Forge history record; the no-baseline-context arm
  is still evaluated against those same frozen results.

For paired comparison, `full` and `no_critic` share the same initial proposal and
iteration-one LEAN result. They branch only after that result: `full` calls the
Critic, while `no_critic` sends `critique=null` to the next Designer call. The
one-shot observation is derived from the same iteration-one artifact.

## Configuration interface

```python
from ablation import load_study

study = load_study("ablation/studies/forge_core.json")
print(study.kind, study.replicates, study.arms)
```

Configuration parsing uses only the Python standard library. Unknown top-level
and arm fields are rejected. Provider credentials remain environment variables
and are never part of a study JSON file.

## Manifest and recovery interface

```python
from ablation import ManifestStore, load_study

study = load_study("ablation/studies/reliability.json")
store = ManifestStore.create(
    "ablation/runs",
    study,
    provenance={"git_commit": "...", "model": "..."},
)
store.register_units([
    {
        "id": "current/1/ML/designer/1",
        "arm": "current",
        "replicate": 1,
        "track": "ML",
        "stage": "designer",
        "external_call": True,
    }
])
store.set_status("running")
store.start_unit("current/1/ML/designer/1")
store.complete_unit(
    "current/1/ML/designer/1",
    artifact="arms/current/1/ML/designer-1.json",
    usage={"total_tokens": 123},
)
```

The scheduler should call `recover_interrupted()` before resuming an unfinished
experiment, then dispatch only `pending_units()`. A completed unit is immutable
and is not returned for rescheduling. If the process ended during an external
call, the recovered unit records `possible_duplicate_external_call=true` because
the model API provides no idempotency key.

`set_frozen_input()` records immutable baseline evidence, initial proposals, or
their digests. `set_artifact()` registers experiment-level results and reports.
Manifest writes use a process lock and atomic file replacement.

## Commands

Validation and cost-shape inspection make no external calls:

```bash
PYTHONPATH=.:backend python -m ablation plan \
  --study ablation/studies/reliability.json
```

Live runs require an explicit confirmation flag. Tracks run in parallel, while
arms, repetitions, and iterations remain ordered:

```bash
PYTHONPATH=.:backend python -m ablation run \
  --study ablation/studies/reliability.json \
  --confirm-live

PYTHONPATH=.:backend python -m ablation run \
  --study ablation/studies/forge_core.json \
  --baseline-history backend/workspace/run_history/forge-2129b60e0453.json \
  --confirm-live
```

`--replicates 1` creates a pilot without changing the versioned study. Resume
and report generation use the persisted config snapshot and completed artifacts:

```bash
PYTHONPATH=.:backend python -m ablation resume \
  --experiment-id <experiment-id> --confirm-live
PYTHONPATH=.:backend python -m ablation status --experiment-id <experiment-id>
PYTHONPATH=.:backend python -m ablation report --experiment-id <experiment-id>
```

When AlphaForge is already running in Docker, the isolated runner can join its
network without changing the production Compose file:

```bash
docker compose -f ablation/compose.yaml run --build --rm runner \
  plan --study /workspace/ablation/studies/forge_core.json
```

## Artifact layout

Each future runner writes one self-contained directory:

```text
ablation/runs/<experiment-id>/
├── manifest.json
├── config.snapshot.json
├── shared/
│   ├── baselines.json
│   └── initial/<replicate>/<track>.json
├── arms/<arm>/<replicate>/<track>/iteration-<n>/
│   ├── proposal.json
│   ├── source.py
│   ├── worker.json
│   ├── details.json
│   ├── critic.json
│   └── trace.json
├── results.jsonl
├── report.json
├── report.csv
└── report.md
```

Raw experiment runs are ignored by Git. They should contain dynamic requests,
responses, normalized Worker results, and the smallest useful log evidence, but
must not contain API keys or repeated static prompt text.

Track pipelines may run in parallel up to `max_parallel_tracks`; iterations
inside one track and experiment arms remain sequential. This protects paired
comparisons and avoids turning Worker or provider contention into an experimental
factor.
