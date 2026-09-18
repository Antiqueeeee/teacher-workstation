"""联系人类表的声明：家长通讯（一学生多监护人）。

类型定义在 `schemas/table_spec.py`，汇总与访问器在 `schemas/registry.py`。
"""

from __future__ import annotations

from app.models.guardian import ROLES as GUARDIAN_ROLES
from app.models.guardian import Guardian
from app.schemas.table_spec import ColumnSpec, FieldSpec, TableSpec
from app.services.guardian_service import link_student

GUARDIAN = TableSpec(
    key="guardians",
    model=Guardian,
    title="家长通讯",
    entity="监护人",
    columns=(
        ColumnSpec("student_name", "学生", w="90px"),
        ColumnSpec("name", "姓名"),
        ColumnSpec("role", "关系", w="76px"),
        ColumnSpec("phone", "电话", w="130px"),
        ColumnSpec("job", "工作单位", w="130px"),
        ColumnSpec("is_primary", "主要联系人", w="100px"),
        ColumnSpec("note", "备注"),
    ),
    fields=(
        # 表单里填的是**学生姓名**，不是 id —— 老师记的是名字。
        # student_id / class_id 由 services/guardian_service.py 的 before_save 解析出来，
        # 同名学生会明确报错让人确认，而不是随便挂到一个同名学生身上
        FieldSpec("student_name", "学生", required=True, hint="填学生姓名；重名时会提示确认"),
        FieldSpec("name", "监护人姓名", required=True),
        FieldSpec("role", "关系", type="select", options=GUARDIAN_ROLES, default="其他"),
        FieldSpec("phone", "电话", hint="手机号或固定电话"),
        FieldSpec("job", "工作单位"),
        FieldSpec("wechat", "微信/其他联系标识"),
        FieldSpec("is_primary", "主要联系人", type="checkbox", default=False, hint="紧急情况优先打这一个"),
        FieldSpec("note", "备注", type="textarea", full=True),
    ),
    search_keys=("student_name", "name", "phone", "job"),
    filter_keys=("role", "is_primary"),
    default_sort=("id", -1),
    class_scoped=True,
    dedupe_keys=("student_name", "name"),  # 同一学生的同一位监护人，重复导入不翻倍
    extra_keys=("student_id",),
    # 把老师填的「学生姓名」解析成 student_id，并带出 class_id 与冗余姓名
    before_save=link_student,
)
