# AlphaForge 团队运行与开发对齐

> 2026-07-26：当前版本已完成参数型 AI 主链、四 Worker 并行回测、
> SQLite 五局三胜对战、跨轮冠军与 AI Coach、运行快照恢复及教学页面。

## 当前系统

AlphaForge 在同一实验合同下运行四个公共基线、一个 Human 策略以及
Traditional、ML、Hybrid 三条 AI 赛道。AI 不读取 Human 代码、参数、结果
或教学反馈。

AI 只返回 `StrategyTemplateSpec` JSON。后端把合法参数注入固定
`template-v1`，因此 LEAN API、特征计算、训练、预测、时间对齐、风控和
证据记录不再由模型临时编写。每条 AI 赛道固定最多三次真实回测；每轮由
Critic 评价并把参数调整方向交回 Designer。最终不会盲目使用最新版，而是
保留三轮中 Sharpe 最高、再看 CAGR、再看较低回撤的一轮。

用户登录后从 Battle Lobby 创建或继续一场五局三胜对战。第一轮冻结股票池、
日期、资金、基准、费用和滑点，并保存四个公共基线；同场后续轮次直接复用
基线证据。Traditional、ML、Hybrid 分别保留跨轮冠军，本轮挑战者未超过旧
冠军时不会替换冠军。每轮结束后，Human 获得可应用的参数建议，AI Coach
则只基于公共基线与 AI 证据指导下一轮的微调、机制轮换或赛道重建。

## 目录

- `agent/designer.py`：结构化参数设计与修订。
- `agent/critic.py`：基于结果的表现评价，不写参数或代码。
- `agent/prompts.py`：紧凑 DSL 和输出形状。
- `backend/app/schemas/strategy_template.py`：模板参数真值源。
- `backend/app/templates/parameterized_strategy.py.tmpl`：固定 LEAN 实现。
- `backend/app/services/strategy_template.py`：校验与确定性编译。
- `backend/app/services/baseline_service.py`：完整实验编排。
- `backend/app/repositories/sqlite_repository.py`：用户、会话、对战和轮次持久化。
- `frontend/src/App.jsx`：登录、对战、参数、轮次、结果、教学和代码展示。
- `docs/PROJECT_ARCHITECTURE_zh.md` / `_en.md`：中英文完整架构说明。
- `docs/BATTLE_SYSTEM_zh.md`：对战、持久化、基线复用和跨轮 Coach 规则。

## 运行

仅修改 `.env` 时通常不需要重建镜像：

```powershell
docker compose up -d --force-recreate backend
```

代码变化后：

```powershell
docker compose up -d --build
docker compose ps
docker compose logs -f backend lean-worker lean-worker-2 lean-worker-3 lean-worker-4 frontend
```

打开 `http://localhost:8501`。先在 Build 页面确认至少 5 只白名单股票和
统一实验设置，再运行 Human 与 AI Forge。第一轮最多包含四个基线、一个
Human 回测及 3 × 3 个 AI 参数回测；同场后续轮次不会重复运行四个基线。
Results 顶部会显示本轮实际使用的冻结参数，R1–R5 可从结果页或 PK Arena
直接切换。

## 开发规则

- 不把 Human 信息加入 Designer/Critic 上下文。
- 不让 Agent 输出 Python 或修改固定模板。
- 新策略自由度必须先作为 schema 字段和模板实现共同加入。
- 所有 schema 合法组合都应可运行；失败时修模板，不增加错误枚举提示词。
- 保留每轮参数、SHA-256、Worker run id、指标和 Critic 报告以便复现。
- 不直接修改 `backend/workspace` 中的 SQLite 或 Run 快照；通过 API 管理历史。
- 对复杂并发和信息边界写“原因型”注释，避免复述代码行为的逐行注释。
- 三轮择优只是开发期模型选择；对外解释时必须同时展示过拟合限制和鲁棒性。

## 测试

```powershell
$env:PYTHONPATH='.;backend'
.\.venv\Scripts\python.exe -m pytest -q backend/tests

cd frontend
npm.cmd test -- --run
npm.cmd run build
```

Docker 实机回测由成员在本地完成；静态测试不能替代三条模板的真实 LEAN
验证。
