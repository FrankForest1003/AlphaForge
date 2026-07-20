# Shared Contracts

Freeze these contracts before the four development tracks diverge:

1. `project_configuration.schema.json`
2. `strategy_manifest.schema.json`
3. `alphaforge_dsl_v1.schema.json`
4. `dsl_validation_result.schema.json`
5. `candidate_lineage.schema.json`
6. `job_status.schema.json`
7. `backtest_result_normalized.schema.json`
8. `agent_event.schema.json`

Do not add placeholder schemas that could be mistaken for frozen contracts. Each schema should be reviewed by all affected module owners and accompanied by valid/invalid fixtures and tests.
