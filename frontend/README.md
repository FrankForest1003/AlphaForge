# AlphaForge Studio

前端是 Vite + React 单页应用，围绕“登录—创建对战—逐轮实验—结果学习”的流程组织。

## 页面与流程

- `Battle Lobby`：查看 SQLite 中持久化的历史对战、当前比分和 R1–R5 状态；可以创建、继续、查看或删除整场对战。
- `Build`：第一轮选择 5–30 只白名单股票并冻结回测设置，通过 Guided Setup 或完整 QuantConnect Python 提交 Human Strategy。后续轮次复用同一实验合同，只调整 Human 策略。
- `AI Forge`：依次展示 Public Evidence、Parallel Entrants、Validate & Compile、Parallel Trial Loops、Judge & Champion 五个真实运行阶段。三个 AI 赛道并行，但每条赛道内部按 LEAN → Critic → Designer 顺序迭代，最多三次。
- `Results`：展示本轮冻结的股票池、日期、资金、基准和交易成本，以及收益、风险、成本、权益曲线和回撤对比。
- `Generated Strategy Reviews`：用精简结果说明候选是否通过执行证据检查；完整参数、Critic 反馈和迭代谱系保留在 AI Forge。
- `Robustness`：展示时期、起点、交易摩擦和股票池扰动下的敏感性结果。
- `Learning Review`：解释本轮最优策略、下一轮 Human 调整建议和相关量化概念。
- `Strategy Code`：查看带语法高亮的 Human 与 AI 编译后源码，并支持一键复制。
- `PK Arena`：按一场真实的五局三胜对战展示逐轮比分、Human/AI 指标和跨轮冠军，而不是把互不相关的最近 Run 拼成一场比赛。

完整代码模式默认加载可运行的 `UserStrategy` 模板。AI Forge 明确执行信息边界：
Human 源码、参数、结果、订单和个性化建议均不进入 Designer、Critic 或 AI Coach 上下文。

Accepted 表示候选通过模板运行与执行证据验收，不代表其一定赢得本轮。赛道内三次试验及跨轮冠军按
Sharpe Ratio、CAGR、较低 Maximum Drawdown 的固定顺序比较；最终 PK 分数使用完整的确定性评分卡。

## 状态同步

前端每 3 秒刷新正在运行的 Forge Run。主回测结束后，如果鲁棒性测试、Teaching Explainer 或
AI Coach 仍在运行，轮询会继续。每次 Run 刷新也同步所属 Battle，因此新轮次不会长期停留在
`Not played`。后端重启后，可从持久化的 Run 快照重新打开已完成结果。

## 本地运行

```powershell
npm.cmd install
npm.cmd run dev
```

开发服务器监听 `8501`，并将浏览器发往 `/api` 的请求代理到
`ALPHAFORGE_API_PROXY_TARGET`，默认是 `http://127.0.0.1:8000`。

项目通常通过根目录 Docker Compose 启动：

```powershell
docker compose up -d --build
docker compose ps
```

Compose 使用同一前端构建，并把 API 代理目标设置为 Docker 网络中的
`http://backend:8000`。

## 测试和构建

```powershell
npm.cmd test -- --run
npm.cmd run build
```
