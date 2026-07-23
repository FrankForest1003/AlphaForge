# AlphaForge Studio

当前前端是 Vite + React 单页应用，提供以下页面：

- `Build`：选择股票候选池和统一回测设置，并通过 Guided Setup 或完整 Python 代码提交 Human Strategy。
- `Results`：自动刷新运行状态，以图表和统一格式的表格比较策略结果，并展示 Generated Strategy 的验收历史。
- `Strategy Code`：查看 Human Strategy 和 Generated Strategy 的完整源码。

完整代码模式默认加载一个可直接修改的 `UserStrategy` 基础模板。

## 本地运行

```bash
npm install
npm run dev
```

开发服务器监听 `8501`，并将浏览器发往 `/api` 的请求代理到
`ALPHAFORGE_API_PROXY_TARGET`，默认是 `http://127.0.0.1:8000`。

## 测试和构建

```bash
npm test
npm run build
```

项目根目录的 `compose.yaml` 使用同一前端构建，并把 API 代理目标设置为
Docker 网络中的 `http://backend:8000`。
