# AlphaForge 团队运行与开发对齐

> 2026-07-24：AI 主链已从“生成代码—修复代码—语义验收”重构为
> “生成参数—模板回测—Critic 评价—Designer 改参—三轮择优”。

## 当前系统

AlphaForge 在同一实验合同下运行四个公共基线、一个 Human 策略以及
Traditional、ML、Hybrid 三条 AI 赛道。AI 不读取 Human 代码、参数、结果
或教学反馈。

AI 只返回 `StrategyTemplateSpec` JSON。后端把合法参数注入固定
`template-v1`，因此 LEAN API、特征计算、训练、预测、时间对齐、风控和
证据记录不再由模型临时编写。每条 AI 赛道固定最多三次真实回测；每轮由
Critic 评价并把参数调整方向交回 Designer。最终不会盲目使用最新版，而是
保留三轮中 Sharpe 最高、再看 CAGR、再看较低回撤的一轮。

## 目录

- `agent/designer.py`：结构化参数设计与修订。
- `agent/critic.py`：基于结果的表现评价，不写参数或代码。
- `agent/prompts.py`：紧凑 DSL 和输出形状。
- `backend/app/schemas/strategy_template.py`：模板参数真值源。
- `backend/app/templates/parameterized_strategy.py.tmpl`：固定 LEAN 实现。
- `backend/app/services/strategy_template.py`：校验与确定性编译。
- `backend/app/services/baseline_service.py`：完整实验编排。
- `frontend/src/App.jsx`：参数、轮次、Critic 建议和最佳轮次展示。

## 运行

仅修改 `.env` 时通常不需要重建镜像：

```powershell
docker compose up -d --force-recreate backend
```

代码变化后：

```powershell
docker compose up -d --build
docker compose ps
docker compose logs -f backend lean-worker frontend
```

打开 `http://localhost:8501`。先在 Build 页面确认至少 5 只白名单股票和
统一实验设置，再运行 Human 与 AI Forge。一次完整 AI 运行包含四个基线、
一个 Human 回测，以及最多 3 × 3 个 AI 参数回测。

## 开发规则

- 不把 Human 信息加入 Designer/Critic 上下文。
- 不让 Agent 输出 Python 或修改固定模板。
- 新策略自由度必须先作为 schema 字段和模板实现共同加入。
- 所有 schema 合法组合都应可运行；失败时修模板，不增加错误枚举提示词。
- 保留每轮参数、SHA-256、Worker run id、指标和 Critic 报告以便复现。
- 三轮择优只是开发期模型选择；对外解释时必须同时展示过拟合限制和鲁棒性。

## 测试

```powershell
$env:PYTHONPATH='.;backend'
.\.venv\Scripts\python.exe -m pytest -q backend/tests

cd frontend
npm.cmd install
npm.cmd run build
```

Docker 实机回测由成员在本地完成；静态测试不能替代三条模板的真实 LEAN
验证。
