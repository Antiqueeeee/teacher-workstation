#!/usr/bin/env python3
"""把演示夹具灌进**开发库**。

三件事必须先说清楚：

1. **这不是迁移工具。** 夹具是卖家给的假数据，只用于开发与联调；真实数据的导入
   走 Excel/CSV 或旧 JSON 导入通路（见 `docs/改造方案/03` §8）。
2. **走的是与 Excel 导入同一条路径**（`services/import_service` 的规范化 + 校验 + 判重），
   所以「夹具能进来」就等于「导入也能进来」，不会出现两套口径。
3. **幂等**：依赖各表的 `dedupe_keys`，重复运行不会让数据翻倍。

用法：
    python tools/load_fixture.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
FIXTURE = BACKEND / "tests" / "fixtures" / "demo_dataset.json"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.config import DATA_DIR  # noqa: E402
from app.db.engine import SessionLocal  # noqa: E402
from app.db.migrate import upgrade_to_head  # noqa: E402
from app.models.class_ import Class  # noqa: E402
from app.schemas.registry import TABLES  # noqa: E402
from app.services import import_service  # noqa: E402

# 旧表 → 新表 的字段映射。只列当前**已实现**的表；后续每做完一张表就加一条
# （完整映射见 docs/改造方案/03 §6.3）。
MAPPINGS: dict[str, dict[str, Any]] = {
    "rules": {
        "source": "rules",
        "fields": {
            "category": "category",
            "title": "title",
            "content": "content",
            "updated": "effective_from",  # 旧应用的「更新日期」当生效日期用
        },
    },
    "templates": {
        # 夹具里这一项已经是新形状（抽取时就做了 scenario→category、body→content），
        # 所以这里是恒等映射 —— 保留结构是为了和 rules 用同一条代码路径。
        "source": "templates",
        "fields": {
            "title": "title",
            "category": "category",
            "tone": "tone",
            "content": "content",
        },
    },
}


def ensure_class(session) -> int:
    class_id = session.scalar(select(Class.id).where(Class.deleted_at.is_(None)).limit(1))
    if class_id is None:
        row = Class(grade="", class_no="", name="演示班级")
        session.add(row)
        session.flush()
        class_id = row.id
    return class_id


def translate(row: dict[str, Any], fields: dict[str, str]) -> dict[str, Any]:
    """按映射搬字段；空值/缺失不写进去，交给新表的默认值。"""
    result: dict[str, Any] = {}
    for old_key, new_key in fields.items():
        value = row.get(old_key)
        if value in (None, ""):
            continue
        result[new_key] = value
    return result


def main() -> int:
    if not FIXTURE.exists():
        print(f"X 找不到夹具：{FIXTURE.relative_to(REPO)}")
        print("  先运行：python tools/extract_demo_fixture.py")
        return 1

    dataset = json.loads(FIXTURE.read_text(encoding="utf-8"))
    print(f"数据目录：{DATA_DIR}（这是开发库，不是交付给老师的数据）")

    upgrade_to_head()

    created_total = 0
    with SessionLocal() as session:
        class_id = ensure_class(session)
        session.commit()

        for key, mapping in MAPPINGS.items():
            spec = TABLES.get(key)
            if spec is None:
                print(f"- {key}：该表还没实现，跳过")
                continue

            source_rows = dataset.get(mapping["source"]) or []
            if not source_rows:
                print(f"- {key}：夹具里没有这个表的数据（旧应用该表本来就是空的）")
                continue

            rows = [translate(row, mapping["fields"]) for row in source_rows]
            try:
                summary = import_service.commit(spec, session, rows, class_id)
            except import_service.ImportFailed as exc:
                # 校验不过就整批回滚 —— 与导入接口的语义一致，不写进去半份
                session.rollback()
                print(f"- {key}：装载被拒绝 —— {exc.message}")
                continue

            session.commit()
            created_total += summary["created"]
            print(f"- {key}：新增 {summary['created']} 条，跳过重复 {summary['skippedCount']} 条")

    print(f"完成：本次新增 {created_total} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
