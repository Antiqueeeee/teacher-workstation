# 给 AI 编码助手的工作说明

本项目的技术约定集中在 **`CONTRIBUTING.md`**，动手前先读它。要点摘录：

- 设计依据是 `docs/改造方案/` 下的 6 份文档。**改代码前先确认相关决策** —— 尤其 `05-部署与访问设计.md` §7，那里列了**已作废、不要实现**的东西。
- **单文件 ≤ 600 行**，超了必须拆；提交前跑 `python tools/check_file_size.py`。
- **分层禁令**：`api/` 不写 SQL、不写业务规则；`services/` 不 import FastAPI；`models/` 不写查询。
- **不得引入任何运行期外网依赖**（客户要求部署环境离线）。
- **不实现**：账号 / 口令 / 权限、备份功能、导出为独立 HTML、桌面外壳。
- 前端是原生 ES Modules，**无构建步骤**；手机端是一等公民。
- **交付形态**：克隆下来 → 跑一次自举（`python tools/bootstrap.py`）→ 双击 `启动.bat` / `启动.command`。
  自带 Python 运行时装在**项目自己的 `runtime/`** 里，不碰用户系统的 Python；老师的
  启动脚本是薄壳（`.bat` 必须 ASCII + CRLF，这条踩过），逻辑全在 `launcher.py`；
  数据在**项目根 `data/`**。改启动脚本后跑 `python tools/check_launch_scripts.py`。

## 怎么把这个项目跑起来（给 AI 助手 / 自动化）

用户可能把仓库地址丢给 AI 助手（WorkBuddy 这类桌面 Agent），让你**替他把服务跑起来**。
照下面做就行，全程不需要 Docker，也不需要往他电脑上装 Python：

```bash
git clone <仓库地址> teacher-workstation && cd teacher-workstation

# 1. 自举：把自带的 Python 运行时与依赖装进项目自己的 runtime/（需要联网一次）
#    判据：跑完 runtime/python.exe（macOS 是 runtime/bin/python3）存在，且能 import app.main
python3 tools/bootstrap.py            # Windows: python tools\bootstrap.py

# 2. 起服务（后台、无窗口；已经在跑时这条命令是幂等的）
runtime/python3 launcher.py --daemon  # Windows: runtime\python.exe launcher.py --daemon

# 3. 确认真的起来了（别只看命令有没有报错）
runtime/python3 launcher.py --status --json
#    → {"ok": true, "running": true, "port": 8723, "lan": "http://192.168.x.x:8723/", ...}

# 4. 停掉
runtime/python3 launcher.py --stop
```

几条必须遵守的：

1. **不要往用户系统里装 Python 依赖**（`pip install` 到全局、conda 装东西、装 Docker 都不行）——
   这个项目自带运行时的目的就是**不动他的环境**；`bootstrap.py` 只往项目目录里装。
2. **用户的电脑上可能没有 Python**：这时先跟他说清楚「需要在 python.org 装一次 Python 3.11，
   装完项目会把运行时放到自己的目录里，他的 Python 不受影响」，或者用自带运行时的交付包。
3. **开机自启不要用别的方式代替**：只能用 `launcher.py --install-autostart`（Windows 注册表
   `HKCU\...\Run`、macOS LaunchAgent），它不需要管理员权限。
4. **判断成功以 `--status --json` 或 `/api/v1/health` 为准**；另外手机访问的前提是
   「那台电脑开着 + 服务在跑 + 手机连同一个 WiFi」。
5. 地址里的端口**以 `--status --json` 给的为准**（8723 被占用时会自动往后找）。
