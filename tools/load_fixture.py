#!/usr/bin/env python3
"""把演示夹具灌进**开发库**。

三件事先说清楚：

1. **这不是迁移工具。** 夹具是卖家给的假数据，只用于开发与联调；真实数据的导入
   走 Excel/CSV 或旧 JSON 导入通路（见 `docs/改造方案/03` §8）。
2. **走的是与 Excel 导入同一条路径**（`services/import_service` 的规范化 + 校验 + 判重 +
   保存前钩子），所以「夹具能进来」就等于「导入也能进来」，不会出现两套口径。
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
from sqlalchemy.orm import Session  # noqa: E402

from app.config import DATA_DIR  # noqa: E402
from app.db.engine import SessionLocal  # noqa: E402
from app.db.migrate import upgrade_to_head  # noqa: E402
from app.models.class_ import Class  # noqa: E402
from app.models.student import Student  # noqa: E402
from app.schemas.registry import get_spec  # noqa: E402
from app.services import import_service  # noqa: E402
from app.services.student_fields import seed_field_defs  # noqa: E402
from app.services.student_service import register_dynamic_tables  # noqa: E402

# 旧表 → 新表 的映射。只列当前**已实现**的表；每做完一张表就加一条
# （完整映射见 docs/改造方案/03 §6.3）。
MAPPINGS: dict[str, dict[str, Any]] = {
    "students": {
        "source": "students",
        "fields": {
            "name": "name",
            "sno": "sno",
            "gender": "gender",
            "birth": "birth",
            "native": "native",
            "boarding": "boarding",
            "politics": "politics",
            "phone": "phone",
            "enroll": "enroll",
            "hobby": "hobby",
            "note": "note",
        },
    },
    "guardians": {
        # 旧应用一行 = 一位学生的「全家联系人」（父亲母亲挤在一行里）；
        # 新模型是「一位监护人一行」，所以这里要展开而不是逐字段搬
        "source": "parents",
        "expand": "expand_guardians",
    },
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
        # 所以这里是恒等映射 —— 保留结构是为了和别的表用同一条代码路径
        "source": "templates",
        "fields": {
            "title": "title",
            "category": "category",
            "tone": "tone",
            "content": "content",
        },
    },
}


def expand_guardians(row: dict[str, Any]) -> list[dict[str, Any]]:
    """把旧应用的一行联系人拆成 0–2 条监护人记录。"""
    student_name = row.get("name") or ""
    primary_role = row.get("guardian") or ""
    shared = {"wechat": row.get("wechat") or "", "note": row.get("note") or ""}

    candidates = (
        ("父亲", "father", "fatherPhone", "fatherJob"),
        ("母亲", "mother", "motherPhone", "motherJob"),
    )
    rows: list[dict[str, Any]] = []
    for role, name_key, phone_key, job_key in candidates:
        if not row.get(name_key):
            continue
        rows.append(
            {
                "student_name": student_name,
                "name": row[name_key],
                "role": role,
                "phone": row.get(phone_key) or "",
                "job": row.get(job_key) or "",
                # 「父母」表示两位都是联系人，这种情况把第一个人标成主要联系人
                "is_primary": primary_role == role or (primary_role == "父母" and not rows),
                **shared,
            }
        )
    return rows


def ensure_class(session: Session) -> int:
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


def backfill_address(session: Session, dataset: dict[str, Any], class_id: int) -> int:
    """把家庭住址补到学生档案上。

    旧应用把地址放在「家长通讯」那一行里，新模型把它当学生档案的一个字段 ——
    所以这里需要跨表补一次；不补的话演示数据里就看不到地址这一列。
    """
    updated = 0
    for row in dataset.get("parents") or []:
        address = (row.get("address") or "").strip()
        name = (row.get("name") or "").strip()
        if not address or not name:
            continue
        student = session.scalar(
            select(Student).where(
                Student.deleted_at.is_(None), Student.class_id == class_id, Student.name == name
            )
        )
        if student is None:
            continue
        payload = dict(student.extra or {})
        if payload.get("address"):
            continue
        payload["address"] = address
        student.extra = payload
        updated += 1
    session.commit()
    return updated


def main() -> int:
    if not FIXTURE.exists():
        print(f"X 找不到夹具：{FIXTURE.relative_to(REPO)}")
        print("  先运行：python tools/extract_demo_fixture.py")
        return 1

    dataset = json.loads(FIXTURE.read_text(encoding="utf-8"))
    print(f"数据目录：{DATA_DIR}（这是开发库，不是交付给老师的数据）")

    upgrade_to_head()

    # 学生字段定义要先生效，否则动态表声明是空的（播种与应用启动时做的是同一件事）
    with SessionLocal() as session:
        seeded = seed_field_defs(session)
        session.commit()
    if seeded:
        print(f"- 学生字段定义：新播种 {seeded} 条")

    # 注册动态表（学生档案）：与 Web 应用启动时是同一个调用，否则 get_spec 拿不到声明
    register_dynamic_tables()

    created_total = 0
    with SessionLocal() as session:
        class_id = ensure_class(session)
        session.commit()

        for key, mapping in MAPPINGS.items():
            spec = get_spec(key)
            if spec is None:
                print(f"- {key}：该表还没实现，跳过")
                continue

            source_rows = dataset.get(mapping["source"]) or []
            if not source_rows:
                print(f"- {key}：夹具里没有这个表的数据（旧应用该表本来就是空的）")
                continue

            if "expand" in mapping:
                rows: list[dict[str, Any]] = []
                expander = globals()[mapping["expand"]]
                for row in source_rows:
                    rows.extend(expander(row))
            else:
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

        patched = backfill_address(session, dataset, class_id)
        if patched:
            print(f"- 学生档案：补上家庭住址 {patched} 条")

    print(f"完成：本次新增 {created_total} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
