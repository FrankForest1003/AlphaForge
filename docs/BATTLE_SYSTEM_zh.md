# AlphaForge 登录、对战与跨轮学习

## 用户流程

1. 用户注册或登录。密码只以带随机盐的 PBKDF2-SHA256 摘要保存，会话令牌只保存 SHA-256 摘要。
2. Battle Lobby 展示该用户的历史对战、比分、轮次和胜者。用户可打开历史对战或创建新对战。
3. 每场对战最多五轮，任一方先取得三胜即结束。对战轮次不使用普通实验的平局带；总分相同则依次用 Sharpe 决胜。
4. 第一轮冻结股票池、日期、初始资金、基准、手续费和滑点；第 2–5 轮只能修改 Human 策略。前端锁定这些控件，后端再次校验合同。
5. 每轮运行统一实验合同下的四个公开基线、一个 Human 策略和 Traditional、ML、Hybrid 三条 AI 赛道。
6. 轮末保存完整结果、确定性分数、胜者、教学内容和 AI Coach 记忆。PK Arena 展示本场最多五轮的双方指标、分数、AI 冠军和建议。
7. 下一轮自动带入用户上一轮策略，并按真实指标给出“当前值 → 推荐值”。Guided 模式可一键应用；代码模式提供明确但不伪造数值的代码级调整方向。
8. 历史对战可以整场删除，SQLite 外键会级联删除全部轮次；正在运行的对战不可删除。

## SQLite 数据

默认数据库为 `backend/workspace/database/alphaforge.db`；Docker 中挂载到
`/runtime/database/alphaforge.db`。该目录被 Git 忽略。

- `users`：用户名与密码摘要。
- `sessions`：30 天会话令牌摘要。
- `battles`：对战状态、双方胜场、轮数和最终胜者。
- `battle_rounds`：Forge run、Human 输入、结果、教学内容与 AI Coach 记忆。

## Run 重启恢复

- 完成的 Forge run 会把完整页面快照写入
  `backend/workspace/run_history/forge-<run_id>.json`，包括基线曲线、Human
  源码、AI 参数/源码、教学内容和鲁棒性结果。
- 历史文件不再按“最近五次”自动删除；五轮限制只属于单场对战规则。
- `/v1/forge-runs/{run_id}` 在内存未命中时按需读取完整快照；旧版摘要文件则从
  SQLite `battle_rounds` 恢复，并重建可用的基线摘要。
- Backend 重启时尚未完成的轮次不能安全续跑，会标记为失败并允许用户开启下一轮；
  已完成的轮次保持可见。

## 跨轮 AI Coach

AI Coach 在一轮结束后读取：

- 四个公开基线的指标；
- 三条 AI 赛道的参数和每次回测指标；
- Critic 对各次 AI 迭代的诊断。

它明确不能读取 Human 的代码、参数、指标或分数。Coach 为三条 AI 赛道分别输出
“保留什么、避免什么、下一轮检验什么”，Designer 在下一轮把这些内容当作经验假设，
而不是盲目复制参数。模型调用失败时，后端根据真实 AI 回测与 Critic 结果生成确定性
fallback，保证下一轮不会被卡住。

## 责任边界

- 能通过 `StrategyTemplateSpec` 的参数由固定模板负责正确运行。
- Designer 只生成参数，Critic 只评价单轮表现，Coach 只总结跨轮 AI 经验。
- Human 与 AI 在同轮严格信息隔离。
- 历史回测改进不代表样本外提升；教学页和 Coach 都要求限制多重测试，并结合鲁棒性实验。

## 启动

代码和 Compose 配置变化后：

```powershell
docker compose up -d --build
docker compose ps
docker compose logs -f backend frontend
```

打开 `http://localhost:8501`，首次使用选择 **Create account**。

## 对战内复用与跨轮冠军

- Round 1 的四个基线会保存完整的指标、曲线和行为证据。Round 2–5 在实验合同不变的前提下直接复用这些结果，不再重复占用四个 LEAN worker。
- Traditional、ML、Hybrid 各自拥有独立的跨轮冠军。新一轮仍会运行最多三次新参数试验，但最终会把本轮最优结果与历史冠军比较。
- 比较顺序固定为：更高 Sharpe Ratio、再比较更高 CAGR、最后比较更低 Maximum Drawdown。新结果没有超过历史冠军时，系统保留旧冠军的参数、代码、指标和证据，并记录来源轮次。
- Designer 只收到公开基线、AI Coach 记忆和本赛道历史冠军，不收到 Human 策略或 Human 结果。历史冠军用于形成有边界的新假设，不会绕过真实回测。
- 结果相关页面顶部提供 R1–R5 独立切换按钮；切换轮次时保留当前页面（Results、AI Forge、Robustness、Learning Review 或 Strategy Code）。
- 从上一轮进入新一轮时，Human Strategy 区域直接显示“当前值 → 推荐值”、目标指标和调整原因。Guided 参数会预填，代码策略则明确标记为手动修改。

## AI Coach 的跨轮决策

Coach 不再默认要求下一轮继续微调同一策略。后端会先根据真实结果为每条 AI 赛道计算：

- 三次试验相对首次试验的 Sharpe、CAGR 与回撤改善；
- 本轮是否仍由历史冠军胜出；
- 当前机制与最强公开基线之间是否存在明显差距。

据此，Coach 在每条赛道选择一种动作：

- `refine_parameters`：已有明显改善，只调整少量参数；
- `rotate_mechanism`：试验趋于停滞或历史冠军仍未被击败，更换一个核心信号、模型或组合机制；
- `rebuild_track`：整条赛道明显落后公开参考，尝试更不同但仍符合模板 DSL 的方案。

Coach 同时给出变更范围、最多修改的参数数量、决策原因和下一轮假设。Designer 必须读取本赛道指令；新方案仍需经过固定模板和真实 LEAN 回测，历史冠军保留规则继续作为安全网。
