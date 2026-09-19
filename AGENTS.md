# 给 AI 编码助手的工作说明

本项目的技术约定集中在 **`CONTRIBUTING.md`**，动手前先读它。要点摘录：

- 设计依据是 `docs/改造方案/` 下的 6 份文档。**改代码前先确认相关决策** —— 尤其 `05-部署与访问设计.md` §7，那里列了**已作废、不要实现**的东西。
- **单文件 ≤ 600 行**，超了必须拆；提交前跑 `python tools/check_file_size.py`。
- **分层禁令**：`api/` 不写 SQL、不写业务规则；`services/` 不 import FastAPI；`models/` 不写查询。
- **不得引入任何运行期外网依赖**（客户要求部署环境离线）。
- **不实现**：账号 / 口令 / 权限、备份功能、导出为独立 HTML、桌面外壳。
- 前端是原生 ES Modules，**无构建步骤**；手机端是一等公民。
- **交付形态**：自带 Python 运行时的目录 + 双击脚本（`启动.bat` / `启动.command`），
  全部启动逻辑在 `launcher.py`；老师的数据在**包根 `data/`**。改启动脚本后跑
  `python tools/check_launch_scripts.py`（`.bat` 必须 ASCII + CRLF，这条踩过）。
