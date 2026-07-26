# AlphaForge Backend

FastAPI 后端协调四个公共基线、Human 策略和三条参数型 AI 赛道。

## AI 主链

1. 第一轮在同一 `RunSettings` 下并行运行四个公共基线；同场后续轮次直接复用冻结证据。
2. Traditional、ML、Hybrid Designer 并行返回结构化策略参数，Human 回测独立执行。
3. Pydantic 校验 `StrategyTemplateSpec`，编译器将规范化参数注入版本化 `template-v1`。
4. 三条 AI 赛道并行运行；每条赛道内部按 LEAN → Critic → Designer 顺序最多迭代三次。
5. 后端按 Sharpe、CAGR、较低最大回撤依次选择本轮最佳试验，再挑战该赛道的跨轮冠军。
6. A1–A5 执行证据、确定性评分卡和 Teaching Explainer 共同形成结果与教学页面。
7. 回合完成后 AI Coach 只读取公共基线和 AI 证据，为下一轮选择微调、机制轮换或重建。
8. Human 策略保持 Guided 或自定义代码入口，不向任何 AI Agent 暴露。

合法参数导致的运行异常属于模板或基础设施缺陷，不进入 Agent 代码修复。

## 关键目录

- `app/schemas/strategy_template.py`：Agent 可用的策略 DSL。
- `app/schemas/agent_strategy.py`：Designer 与 Critic 输出契约。
- `app/templates/parameterized_strategy.py.tmpl`：固定 LEAN 模板。
- `app/services/strategy_template.py`：校验和编译器。
- `app/services/baseline_service.py`：并行编排、三轮迭代、历史恢复和跨轮择优。
- `app/repositories/sqlite_repository.py`：用户、会话、对战、轮次和 Coach 记忆。

## 并发与持久化

- 一个 API 进程串行编排顶层 Forge Run，单个 Run 内并行执行四个基线、三个 Designer 和三条候选赛道。
- 四个 LEAN Worker 共享只读市场数据，但任务、锁、配置和结果目录彼此隔离。
- SQLite 使用 WAL 模式保存登录和对战状态；`backend/workspace/run_history` 保存完整 Forge 页面快照。
- Run 快照采用临时文件替换，并在同一锁内读取最新内存状态，避免旧的 `pending` 快照覆盖异步生成的 `completed` 教学结果。
- 恢复时完整 Run JSON 是曲线、代码和候选证据的来源；SQLite 中更新的终态教学和轮次信息会覆盖较旧快照。

## 静态测试

```powershell
$env:PYTHONPATH='.;backend'
.\.venv\Scripts\python.exe -m pytest -q backend/tests
```
