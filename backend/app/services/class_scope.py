"""班级归属解析：编辑接口与导入接口共用同一份逻辑。

单班级场景下前端**不需要传 classId**（老师自己部署，通常就一个班，不该被班级概念打扰）；
多班又没指定时明确报错，而不是静默写错班 —— 这是「多班」这个需求最容易翻车的地方。

另外两件与班级有关的小事也放这里，避免各处再写一遍：
`class_label`（班级的展示名怎么拼）、`find_class`（老师写的班级名怎么认出是哪个班 ——
课程模块的班级块、成绩的班级归属都要它）。

还有一类表：`class_from_hook`（班级由钩子从别的表推出来，见 `TableSpec` 的说明）——
对它们 `resolve_class_id` 只认显式传来的 classId，不回退到「唯一的那个班」。

（依赖 `app.api.errors` 是刻意的：那个模块不含任何 FastAPI 依赖，服务层仍然可以脱离
HTTP 单测，符合 CONTRIBUTING §2 的约束。）
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import CLASS_ID_REQUIRED, INVALID_VALUE, ApiError
from app.models.class_ import Class
# 从 table_spec 直接取类型，**不要走 registry**：registry 会 import 各域的
# specs，而 specs 又要 import 服务层的钩子 —— 走 registry 就成了循环导入
from app.schemas.table_spec import TableSpec
from app.services.params import as_int


def resolve_class_id(spec: TableSpec, raw: Any, session: Session) -> int | None:
    """返回本次操作应归属的班级 id；非班级范围的表返回 None。

    三种情况：
    - `class_scoped=False`（话术模板这类全班共用的素材）：没有班级，返回 None；
    - `class_from_hook=True`（课程名单/课程成绩：班级从「这门课教哪个班」推出来）：
      **只认显式传来的 classId**，不回退到「唯一的那个班」—— 回退是猜，而钩子马上就
      会把它改掉，猜错也只是白报一次错；
    - 其余：classId 优先，没传且只有一个班时用那个班，多班又没传则明确报错。
    """
    if not spec.class_scoped:
        return None

    if raw not in ("", None):
        class_id = as_int(raw, "classId")
        if session.get(Class, class_id) is None:
            raise ApiError(INVALID_VALUE, "指定的班级不存在", detail={"classId": class_id})
        return class_id

    if spec.class_from_hook:
        return None

    ids = list(session.scalars(select(Class.id).where(Class.deleted_at.is_(None))))
    if not ids:
        raise ApiError(CLASS_ID_REQUIRED, "还没有班级，请先创建班级", status=409)
    if len(ids) > 1:
        # 界面上暂时没有班级切换器（多班在后续阶段），所以这句话必须说实话，
        # 不能让用户去找一个不存在的东西
        raise ApiError(
            CLASS_ID_REQUIRED,
            "这份数据里有多个班级，而当前版本还没有班级切换界面（多班在后续阶段）。",
            status=409,
        )
    return ids[0]


def class_label(row: Class) -> str:
    """班级的展示名：有年级与班号就拼起来，否则退回它自己的名字。

    课程模块的班级块要显示「高二(3)班」这种写法，而 `classes` 里 grade 与 class_no
    是两个字段（旧应用靠字符串拼，拼错就凭空多出一个班）。
    """
    joined = f"{row.grade}{row.class_no}".strip()
    return joined or row.name


def _normalize(text: str) -> str:
    """比对班级名时统一括号形状与空白 —— 老师手写「高二(3)班」与库里存的
    「高二（3）班」是同一个班，不该因为一个半角括号就报「查无此班」。"""
    return (
        str(text or "")
        .strip()
        .replace("(", "（")
        .replace(")", "）")
        .replace(" ", "")
        .replace("\u3000", "")
    )


def find_class(session: Session, text: str) -> tuple[Class | None, str | None]:
    """按老师写的班级名找班级。返回 `(班级, 一句问题)`。

    **查无此班、重名都不猜**（与 `roster.find_student` 同一条纪律）：
    猜错的后果是把 A 班的课与成绩记到 B 班上，而且不会报错。
    """
    wanted = _normalize(text)
    if not wanted:
        return None, "要填班级名称"
    rows = list(session.scalars(select(Class).where(Class.deleted_at.is_(None))))
    matched = [row for row in rows if wanted in {_normalize(class_label(row)), _normalize(row.name)}]
    if not matched:
        known = "、".join(class_label(row) for row in rows) or "（一个班都还没有）"
        return None, f"没有叫「{text}」的班级。现有班级：{known}（可在「设置」里改班级名）"
    if len(matched) > 1:
        return None, (
            f"有 {len(matched)} 个班都叫「{text}」，系统分不清是哪一个。"
            "请在「设置」里把它们的年级/班号写清楚（如 高二(3)班）。"
        )
    return matched[0], None
