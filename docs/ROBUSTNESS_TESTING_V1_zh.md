# AlphaForge 策略鲁棒性测试 v1

## 目的

主回测回答“策略在一套设置下表现如何”，鲁棒性测试回答“轻微改变时间、成本或
股票集合后，策略是否仍能运行并保留基本收益风险特征”。鲁棒性结论由 Backend
确定性计算，不交给 LLM 裁决，也不允许 Agent 在压力测试期间修改源码。

该功能位于前端 `Robustness` 页面。Forge 主流程完成后，可选择：

- `Best accepted AI`：当前通过 Acceptance 的最佳 AI 候选；
- `Human strategy`：本轮用户策略。

Backend 会冻结该策略的完整源码，然后按顺序提交独立 LEAN 回测。

## v1 压力场景

1. `Recent-regime slice`
   - 只改变开始日期，使用原区间后 40% 左右的数据，且尽量保留至少一年；
   - 检查策略是否只依赖早期市场阶段。
2. `Delayed-start sensitivity`
   - 将开始日期后移最多 126 个自然日；
   - 检查结果是否高度依赖单一入场日期。
3. `Double-friction stress`
   - 交易费率与滑点同时变为原来的两倍；
   - 检查换手和成本敏感性。
4. `Deterministic universe dropout`
   - 当股票数量大于 5 时，按固定顺序删除每第五只股票；
   - 检查策略是否依赖个别股票；
   - 当原始集合只有 5 只时跳过，避免违反统一最低 5 只股票的约束。

所有场景继续使用相同初始资金、Benchmark、剩余股票顺序及策略代码。场景不是参数
寻优，不会搜索“表现最好”的日期、费用或股票子集。

## 确定性检查与评分

每个实际执行的场景有四项等权检查：

1. LEAN 正常完成；
2. 存在成交且最大总敞口大于零；
3. CAGR 保留：
   - 时间/股票扰动至少达到主结果 CAGR 的 35%；
   - 双倍成本至少达到主结果 CAGR 的 70%；
4. 风险控制：
   - Sharpe 大于零；
   - 最大回撤不超过 `min(60%, max(35%, 主回撤 + 15%))`。

总分是通过检查数量占全部检查数量的百分比：

- `75–100`：Robust；
- `50–74.9`：Mixed；
- `< 50`：Fragile；
- 少于三个有效场景或少于两个完成场景：Insufficient。

这些阈值是课程演示用的可解释筛查规则，不是投资行业统一标准。

## 使用方法

1. 完成一轮 Forge Run；
2. 打开左侧 `Robustness`；
3. 选择 Best accepted AI 或 Human strategy；
4. 点击 `Run Robustness Test`；
5. 页面轮询当前 Run，并展示每个场景的 CAGR、Sharpe、回撤、收益保留率和检查数。

API：

```http
POST /api/v1/forge-runs/{run_id}/robustness
Content-Type: application/json

{"target": "best_ai"}
```

也可以使用 `{"target": "human"}`。

## 解释边界

- 这是多场景历史回测，不证明未来收益；
- Designer 在生成时看过完整时期的公共基线证据，所以 recent-regime 只是
  pseudo-out-of-sample，不应称为严格盲测；
- v1 故意不做大规模参数扫描，避免把“鲁棒性测试”变成第二轮过拟合；
- Final Blind Challenge 应使用完全未进入设计、修复和基线比较流程的新时间窗口。
