# AlphaForge Backend

FastAPI Backend 校验七项 RunSettings，并编排四个公共基线、一个 Human 策略、三个 Designer 候选、Repair 和 Acceptance Agent 闭环。Agent 的 DeepSeek 客户端、提示词和角色实现位于仓库根目录 `agent/`。

运行状态保存在内存中，同一时间只编排一个 Forge Run。三个 Designer 的首次 DeepSeek 请求并行执行；策略任务由 Worker 串行执行。

Human 策略支持两种输入。`code` 模式提交完整 `UserStrategy` Python 源码；`guided` 模式提交信号、回看期、调仓频率和持仓数，Backend 生成完整源码。Human 由 Worker 直接回测并返回指标、行为事实和源码，不进入 Repair 或 Acceptance。

DeepSeek 使用环境变量 `API_KEY`、`BASE_URL`、`MODEL` 和 `THINKING_ENABLED`。官方 QuantConnect Writing Algorithms Python 纯文本在进程启动时读取，并作为每次 Designer 和 Repair 请求的完整固定上下文。

候选运行失败后，Backend 把完整日志、完整源码、RunSettings 和 Worker 结果交给 Repair。候选运行成功后，Backend 读取 Worker 行为明细，构造精确事实并交给 Acceptance Agent 检查 A1–A5。验收否决报告进入 Repair；修复后必须重新回测和重新验收。运行失败与验收否决共享最多三次源码修改。

Acceptance Agent 不接收 LEAN 文档、QC 模板或基线结果。候选只有在实际投资行为、数据到订单因果链、轨道完整性、时间完整性和共享设置全部通过后才进入 `accepted`。API 返回最后验收报告和完整验收历史；累计 token 包含 Designer、Repair 和 Acceptance 调用。

`AlphaForgeBaseAlgorithm` 为所有策略设置固定 2% 购买力缓冲。Designer 模板使用内部 95%最大总仓位，但不设置统一单标的仓位上限，并给出单标的和多标的 History DataFrame 范式；日线 long-only 组合通过 `af_rebalance_to_weights` 等待减仓成交后再提交买单。这些不是 RunSettings 字段。

接口：

- `GET /v1/health`
- `GET /v1/catalog/universe`
- `GET /v1/catalog/baselines`
- `POST /v1/forge-runs`，请求体包含 `settings` 和 `human_strategy`
- `GET /v1/forge-runs/{run_id}`

本地测试：

```bash
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q
```
