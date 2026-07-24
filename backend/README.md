# AlphaForge Backend

FastAPI 后端协调四个公共基线、Human 策略和三条参数型 AI 赛道。

## AI 主链

1. 在同一 `RunSettings` 下运行四个公共基线。
2. Traditional、ML、Hybrid Designer 仅返回结构化策略参数。
3. Pydantic 校验 `StrategyTemplateSpec`。
4. 后端把参数注入版本化 `template-v1`，生成确定性 LEAN 源码。
5. 每轮回测完成后由 Critic 评价表现并给出有界改参建议。
6. Designer 根据 Critic 报告重写完整参数，每条赛道最多三次回测。
7. 后端按 Sharpe、CAGR、较低最大回撤依次选择该赛道最佳轮次。
8. Human 策略保持 Guided 或自定义代码入口，不向 AI 暴露。

合法参数导致的运行异常属于模板或基础设施缺陷，不进入 Agent 代码修复。

## 关键目录

- `app/schemas/strategy_template.py`：Agent 可用的策略 DSL。
- `app/schemas/agent_strategy.py`：Designer 与 Critic 输出契约。
- `app/templates/parameterized_strategy.py.tmpl`：固定 LEAN 模板。
- `app/services/strategy_template.py`：校验和编译器。
- `app/services/baseline_service.py`：基线、三轮迭代、历史和择优。

## 静态测试

```powershell
$env:PYTHONPATH='.;backend'
.\.venv\Scripts\python.exe -m pytest -q backend/tests
```
