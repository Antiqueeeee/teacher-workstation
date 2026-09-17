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
# 后端（开发模式；手机与电脑都通过内网地址访问）
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8723 --reload
# → 手机或电脑访问 http://<本机内网IP>:8723/

# 前端无构建步骤，由后端静态托管，无需单独起服务
```

> 数据目录默认在 `backend/data/`（不入库）。环境尚未安装，见根 `README.md` 的「当前状态」。
