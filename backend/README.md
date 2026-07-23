# AlphaForge Backend

FastAPI Backend 校验七项 RunSettings，并编排四个公共基线、一个 Human 策略、三个 Designer 候选、Repair 和 Acceptance Agent 闭环。Agent 的 DeepSeek 客户端、提示词和角色实现位于仓库根目录 `agent/`。

运行状态保存在内存中，同一时间只编排一个 Forge Run。三个 Designer 的首次 DeepSeek 请求并行执行；策略任务由 Worker 串行执行。

Human 策略支持两种输入。`code` 模式提交完整 `UserStrategy` Python 源码；`guided` 模式提交信号、回看期、调仓频率和持仓数，Backend 生成完整源码。Human 由 Worker 直接回测并返回指标、行为事实和源码，不进入 Repair 或 Acceptance。

DeepSeek 使用环境变量 `API_KEY`、`BASE_URL`、`MODEL` 和 `THINKING_ENABLED`。官方 QuantConnect Writing Algorithms Python 纯文本在进程启动时读取，并作为每次 Designer 和 Repair 请求的完整固定上下文。

候选运行失败后，Backend 从 Worker details 提取失败订单、订单事件、失败前最近组合快照和对应日志原文，并连同完整源码、RunSettings、Worker 结果证据视图和控制台日志证据视图交给 Repair。常规大小的结果和日志原样发送；超过上下文预算时，证据视图保留错误邻域、开头、结尾、原始长度和省略标记。完整 `result.json` 与完整日志始终保存在 Worker Attempt Trace。候选运行成功后，Backend 读取 Worker 行为明细，构造订单、持仓、信号、模型训练、预测、分阶段调仓开始/完成/替换和取消订单事实并交给 Acceptance Agent 检查 A1–A5。验收否决报告进入 Repair；修复后必须重新回测和重新验收。运行失败与验收否决共享最多三次源码修改。

Acceptance Agent 不接收 LEAN 文档、QC 模板或基线结果。候选只有在实际投资行为、数据到订单因果链、轨道完整性、时间完整性和共享设置全部通过后才进入 `accepted`。API 返回最后验收报告和完整验收历史；累计 token 包含 Designer、Repair 和 Acceptance 调用。

`AlphaForgeBaseAlgorithm` 只提供手续费、滑点、benchmark、History DataFrame 和行为记录辅助。策略使用标准 QuantConnect 生命周期，并自行决定组合规模、现金预留和订单过程。四个固定 Baseline 显式选择分阶段执行工具。Designer 和 Repair 模板提供可选的 `self.af_rebalance_daily_weights`：Daily 组合轮换需要依赖卖出资金时，它等待移除和减仓成交后再按完整 Daily bar 计算买单；目标权重和总敞口仍完全由策略传入。

Designer 和 Repair 模板说明本地股票数据为 Daily，并展示 `af_split_history_frames` 返回值按大写 ticker 字符串取值的方式。使用分阶段 helper 时，信号或预测期限、目标更新频率和多 Daily bar 执行周期保持一致，使每轮目标在下一目标到来前完成。策略通过 `af_record_signal`、`af_record_ml_training` 和 `af_record_ml_prediction` 记录实际执行路径。DeepSeek 返回空内容或非法 JSON 时，客户端关闭 Thinking 后重试一次；连接异常直接返回调用失败。

接口：

- `GET /v1/health`
- `GET /v1/catalog/universe`
- `GET /v1/catalog/baselines`
- `POST /v1/forge-runs`，请求体包含 `settings` 和 `human_strategy`
- `GET /v1/forge-runs/{run_id}`

本地测试：

```bash
PYTHONPATH=.:backend .venv/bin/python -m pytest backend/tests -q
```
