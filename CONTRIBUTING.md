# 开发约定

> 设计依据是 `docs/改造方案/` 下的 6 份文档。**改代码前先确认相关决策** —— 尤其 `05-部署与访问设计.md` §7，那里列了**已作废、不要实现**的东西（账号/口令/权限、备份、导出独立 HTML、桌面外壳、按 32 位 Win7 的适配、任何运行期外网调用）。

---

## 1. 项目结构

```
teacher-workstation/
├── backend/                # FastAPI + SQLAlchemy + SQLite
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py         # 应用装配：中间件、静态托管、异常处理
│   │   ├── config.py       # 数据目录、端口、常量
│   │   ├── db/             # 引擎、Base、Alembic 迁移
│   │   ├── models/         # SQLAlchemy 模型，一个聚合一个文件
│   │   ├── schemas/        # Pydantic 模型 + 表注册表
│   │   ├── api/v1/         # HTTP 路由（含 crud_factory 工厂）
│   │   ├── services/       # 业务规则与统计口径
│   │   └── storage/        # 数据目录、媒体落盘、体积统计
│   └── tests/              # pytest；fixtures/ 放演示夹具
├── frontend/               # 原生 ES Modules，无构建步骤
│   ├── index.html
│   ├── src/{core,components,pages}/
│   └── styles/
├── tools/                  # check_file_size.py、夹具装载、迁移工具
├── docs/改造方案/           # 设计与决策文档（6 份）
├── raw-material/           # 原始素材：待移植的旧应用 HTML（只读参考）
└── .validation/            # 本地环境与验证产物（不入库）
```

---

## 2. 分层与职责

| 层 | 可以做什么 | **禁止** |
|---|---|---|
| `backend/app/api/` | 取参、校验、调 service、返回 schema | **不写 SQL、不写业务规则** |
| `backend/app/services/` | 业务规则、统计口径 | **不 import FastAPI**（保证可独立单测） |
| `backend/app/models/` | 表与关系的定义 | **不写查询逻辑** |
| `backend/app/schemas/` | Pydantic 模型、序列化 | 不碰数据库 |
| `backend/app/storage/` | 数据目录、媒体落盘、体积统计 | 不感知 HTTP |
| `frontend/src/core/` | api / store / router / dom / format / errors | **不反向引用 pages、components** |
| `frontend/src/components/` | 通用 UI（crud-page、form、charts…） | 不写具体页面的业务 |
| `frontend/src/pages/` | 页面组装与渲染 | 不直接 `fetch`（统一走 `core/api.js`） |

依赖方向**单向**：`pages → components → core`。

前两条禁令**有测试守着**（`backend/tests/test_layering.py`）：
`api/` 里出现 SQL 或 `services/` 里 import FastAPI 都会让测试红掉
（唯一豁免是 `api/v1/crud_factory.py` —— 它本身就是「把表声明变成一组查询」的生成器）。
「学新接口时顺手来一句 `select(...)`」太自然了，所以这条不能只写在文档里。

### 2.1 两个与「归属」有关的约定

- **班级归属**：大多数表是 `class_scoped=True`，`class_id` 由 `resolve_class_id`
  从 `classId` 参数或「唯一那个班」解析出来。**但有一类表的班级是从别的表推出来的**
  （课程名单、课程成绩的班级来自「这门课教哪个班」）—— 这类表声明
  `class_from_hook=True`：`resolve_class_id` 只认显式传来的 `classId`，不回退到
  「唯一的那个班」（否则多班部署下建一条课程名单会先报「还没有班级切换界面」，而它
  根本不需要班级切换），钩子负责把 `class_id` 写进去（那一列 NOT NULL，漏写会当场报错）。
- **写请求的提交时机**：POST/PUT/PATCH/DELETE 的提交发生在**响应发出之前**
  （`api/committing_route.py`，由注册路由时的 `route_class` 统一生效，
  新加接口不会漏）。FastAPI 的 yield 依赖在响应之后才收尾，只靠它的话
  「磁盘满 / 库被锁 / 约束到提交才炸」都会让客户端先拿到 `200 已保存`。
  测试见 `tests/test_smoke.py::test_write_returns_500_when_the_commit_fails`。

---

## 3. 单文件行数（硬约束）

- 单文件 **≤ 600 行**（含注释与空行），**没有例外**。
- 目标值：后端 ≤ 400 行，前端 ≤ 300 行，页面目录内文件 ≤ 500 行。
- 提交前跑：`python tools/check_file_size.py`（超限退出码非 0）。
- 拆分手法，优先级从高到低：
  1. **按职责分** —— 路由 / 服务 / 模型 / 序列化（后端）、渲染 / 配置 / 事件处理（前端）；
  2. **按子功能分** —— 一个页面目录下的多个子模块；
  3. **按聚合分** —— 一张表或一组紧密相关的表一个模型文件。
- **禁止**：为压行数把多段逻辑塞进一行、把常量内联、用 `eval` 拼装、拆成语义不明的 `utils2.js`。**行数上限是问题信号，不是目的。**

---

## 4. 离线约束（硬规则）

客户要求部署环境不联网，所以：

- 代码里**不得出现任何指向外网的地址** —— CDN、外部字体、外部图标、统计上报、在线更新检查、远程授权，一个都不行。
- 前端资源：图标用**内联 SVG**，字体用**系统字体栈**。
- 依赖安装只发生在开发机；交付时要能把依赖整体带走（`pip download` / `pip wheel`，见 `docs/改造方案/03` §9.3）。
- 唯一例外是**课程表 OCR**：它默认关闭，界面上写明「此功能需要联网，当前环境不可用」，既不静默失败也不弹报错。

---

## 5. 数据库

- SQLite，开启 **WAL**、`foreign_keys=ON`、`busy_timeout=5000`。
- 表结构变更一律走 **Alembic**，**一版一文件**，不手改库。
- 迁移脚本要向前兼容（优先加列，避免破坏性改列），方便回滚。
- **金额以「分」存整数**；时间字段统一类型，不要混用字符串与日期。
- 学生关联一律用 `student_id`，`name` 只作冗余展示列；学号唯一约束是 `(class_id, sno)`。
- **数据库地址只在 `app/config.py` 定义一处**，`alembic.ini` 不重复配置（由 `env.py` 覆盖），避免迁移和运行时连到两个不同的库。
- **`alembic.ini` 这类被 `configparser` 读取的配置文件必须纯 ASCII** —— Windows 中文环境下它按 GBK 解码，一旦写入中文注释，所有 Alembic 命令会直接崩（这个坑已经踩过一次，见提交记录）。

---

## 6. 前端

- 原生 ES Modules，**无构建步骤**，`index.html` 直接引 `<script type="module">`。
- 渲染沿用「**返回 HTML 字符串 + `bind(root)` 绑事件**」的写法 —— 现有 33 页都是这个模式，改造成本最低，不要中途换范式。
- 数据一律走 `core/api.js`，页面不直接 `fetch`；错误码到中文提示的映射也在那一层。
- **手机端是一等公民**：窄屏单列、表格转卡片（复用 `cardView`）、弹窗转全屏抽屉；**在真实手机上验收**，不看开发者工具模拟视图。
- 浏览器基线：近两年的 Chrome / Edge / Firefox 与对应手机浏览器；避免刚落地的实验特性（容器查询、View Transitions）。注意部署环境不联网 → **浏览器不会自动更新**。

---

## 7. 测试

- `pytest`。
- **统计口径类必须有单测**：出勤率、作业提交率、成绩排名与及格线、团员占比、金额合计 —— 且要能复现改造前会失败的情形。
- 演示夹具在 `backend/tests/fixtures/demo_dataset.json`（来自旧应用的种子数据，是**假数据**，只作对照与联调）。
- 不追求覆盖率数字，追求「**已知的坑都有测试**」。

---

## 8. 提交信息

Conventional Commits 风格，描述用中文：

```
feat(students): 学生档案支持动态字段
fix(dorms): 改容量改用模态框，替换 prompt()
refactor(crud): 抽出通用 CRUD 路由工厂
docs: 补充多班维度的说明
chore: 初始化仓库与开发约定
```

---

## 9. 本地怎么跑

```bash
# 1. 装依赖（本仓库用 .validation/conda，Python 3.11）
../.validation/conda/python.exe -m pip install -r backend/requirements-dev.txt

# 2. 起服务（开发模式：热重载；手机与电脑都通过内网地址访问）
cd backend
PYTHONPATH=. ../.validation/conda/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8723 --reload
# → http://<本机内网IP>:8723/

# 或者用一键启动器（与老师走的那条路完全一致）
cd ..
../.validation/conda/python.exe launcher.py           # 前台
../.validation/conda/python.exe launcher.py --daemon  # 后台
../.validation/conda/python.exe launcher.py --stop    # 停止

# 3. 跑测试
cd backend && PYTHONPATH=. ../.validation/conda/python.exe -m pytest -q

# 4. 提交前检查
python tools/check_file_size.py
python tools/check_frontend.py
python tools/check_launch_scripts.py
```

- 首次启动会自动建目录、跑数据库迁移，并创建一个**空的**默认班级（不是演示数据）。
- 数据目录默认是**包根目录的 `data/`**（已 gitignore；第六阶段从 `backend/data/` 改过来的），
  可用 `TWS_DATA_DIR` 覆盖。
- 前端无构建步骤，由后端静态托管，不用单独起服务。
- 数据库结构变更：先改模型并在 `app/models/__init__.py` 里导出，然后
  `cd backend && alembic revision --autogenerate -m "..."`，**检查生成的脚本**再 `alembic upgrade head`。

---

## 10. 交付包与启动脚本

老师拿到的是**一个目录**：自带 Python 运行时（`runtime/`，gitignore 掉，交付时构建进去）、
程序代码、双击脚本、以及 `data/`（第一次启动时自动建）。

- **所有启动逻辑在 `launcher.py`**（跨平台，可单测）：找空闲端口、建数据目录、显示地址、
  开浏览器、已在跑时不重复启动、`--daemon` / `--stop` / `--status` / `--install-autostart`。
  那一堆 `启动.bat` / `启动.command` 只是**薄壳**，不要在脚本里写逻辑；
- **`.bat` 有两条硬规矩**（都踩过）：必须是 **CRLF**（LF 会被 cmd 拼成乱命令）、
  **只允许 ASCII**（中文注释会被按代码页切碎当命令执行）。中文提示一律交给 Python 打印；
- `.command` / `.sh`：**LF + shebang + 可执行位**（macOS 双击靠它）；交付打包时要保住可执行位；
- `python tools/check_launch_scripts.py` 守这几条 —— 改脚本后跑一下，别等老师双击了才发现；
- **验证方式**：在包根目录把 `.bat` 复制成 ASCII 名（如 `_t_start.bat`）再用 `cmd /c` 跑一遍
  （Git Bash 里直接传中文文件名给 cmd 会有编码错配，那是测试环境的假象）。
- **仓库存的行尾 vs 交付包的行尾**：git 仓库里统一存 LF，只在 checkout 时按 `eol=` 转换；
  所以 `.gitattributes` 里必须留 `*.bat text eol=crlf`、`*.command text eol=lf`（`check_launch_scripts.py` 守着）。
  **从仓库直接打 zip 时连 checkout 都没有** —— 交付包的构建脚本必须自己把 `.bat` 转成 CRLF、
  给 `.command` 加上可执行位（0o755），否则老师那边双击就是坏的。

### 10.1 开发机上怎么假装成交付包

交付包里 `runtime/` 是自带的 Python。开发机上不必真造一份，用一个目录链接代替就行：

```bash
cmd //c "mklink /J runtime D:\CodeSpace\teacher-workstation\.validation\conda"
```

然后双击（或用 `cmd /c`）根目录的 `启动.bat` 就是老师的体验 —— 数据会落在 `<包根>/data/`。

### 10.2 怎么构建真正的交付包

```bash
# Windows（在 Windows 上）
python tools/build_bundle.py --platform windows-x64
# macOS（**必须在 macOS 上**，见下）
python tools/build_bundle.py --platform macos-arm64     # 或 macos-x64
```

它做四件事（`tools/build_bundle.py`）：

1. 下 python-build-standalone 的 `install_only` 运行时（可搬移，专为分发设计）→ `runtime/`；
2. 按 `backend/requirements.txt` 下**轮子**到 `vendor/wheels/<平台>/`（缓存下来，下次 `--offline` 不再联网），
   再解开进运行时的 site-packages —— 目标机器不需要 pip、不需要网络；
3. 拷代码 + `launcher.py` + 双击脚本 + 使用说明，**跳过** `data/`、`tests/`、`raw-material/` 等；
4. 收拾行尾与权限（`.bat` → CRLF、`.command` → 755）并打 zip（带顶层目录）。

构建完它会**自己验一遍**：用交付包里的运行时导入全部依赖，再真起一次服务、查一次状态、停掉。
产物在 `dist/班主任工作台-<平台>-<版本>.zip`（约 48 MB）。

**为什么 macOS 包必须在 macOS 上构建**：macOS 运行时压缩包里含符号链接
（`bin/python3 → python3.11`），在 Windows 上解压会变成普通文件，到 Mac 上就坏了。
构建脚本会直接拒绝（`TWS_BUILD_CROSS=1` 可强行跳过，但未验证）。

---

## 11. 远端与推送

代码同时放在两个地方，**一次 push 推两边**：

```bash
git push origin main        # origin 配了两个 push 地址，这一条命令推到 GitHub 与 Gitee
```

- `origin` 的 fetch 地址是 GitHub，push 地址有两个（GitHub + Gitee）：
  `git remote -v` 能看到三行（一行 fetch、两行 push）。
- 拉取只从 GitHub 拉；Gitee 只作为镜像（备一份，也方便国内网络访问）。
- 新加远端地址用 `git remote set-url --add --push origin <url>`，**不要**用
  `git remote add`（那会又多一个远端，`git push` 就不会一次推两边了）。
- 两个仓库都是**公开**的 —— 往仓库里加东西前先想一下「这个能公开吗」：
  原始素材（`raw-material/meetings`、`discussion`）、老师的数据（`data/`）都已 gitignore，
  别用 `git add -f` 把它们塞进去。
