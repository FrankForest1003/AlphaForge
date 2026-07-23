# AlphaForge Frontend

Streamlit 工作区提供：

- 30 只本地股票的 checkbox 候选池；
- 日期、初始资金、benchmark、交易费和滑点设置；
- 引导式策略构建器和完整 Python 源码编辑器；
- 创建运行、自动轮询实时进度和策略源码三个导航视图；
- URL `run_id` 定位和打开已有运行；
- 参考策略、用户策略和生成策略的状态与回测摘要；
- 用户策略与生成策略的完整源码展示和下载；
- 生成策略的审查历史、行为事实、修改请求和累计 token。

前端只通过 `ALPHAFORGE_API_BASE_URL` 访问 Backend，不包含本地 Mock 数据。

本地测试：

```bash
PYTHONPATH=frontend .venv/bin/python -m pytest frontend/tests -q
```
