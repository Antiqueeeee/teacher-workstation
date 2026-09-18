"""v1 路由汇总：注册表接口 + 每张表的通用 CRUD + 动态表。

顺序有讲究：
1. 字面路径（`/students/fields`）必须在泛化路径（`/students/{row_id}`）之前注册，
   否则 `fields` 会被当成 id 解析；
2. 动态表（学生档案）的路由由 `register_dynamic_routers` 在 `create_app` 里挂载 ——
   它们的声明是每次请求现算的，不能在这里就固化成一份。
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from app.api.v1.attendance_day import router as attendance_day_router
from app.api.v1.crud_factory import build_router
from app.api.v1.dorms import router as dorms_router
from app.api.v1.exams import router as exams_router
from app.api.v1.export import router as export_router
from app.api.v1.student_fields import router as student_fields_router
from app.api.v1.student_reports import router as student_reports_router
from app.api.v1.transfer import router as transfer_router
from app.config import APP_VERSION
from app.schemas.registry import DYNAMIC_TABLES, TABLES, all_specs

router = APIRouter(prefix="/api/v1")


@router.get("/health", tags=["系统"])
def health() -> dict:
    return {"ok": True, "data": {"version": APP_VERSION, "tables": len(all_specs())}}


@router.get("/meta/registry", tags=["系统"])
def registry() -> dict:
    """全部表的声明，前端据此渲染列表/表单/筛选项，避免两边各写一遍。

    动态表现算，所以老师加完字段刷新页面就能看到，不必重启服务。
    """
    return {"ok": True, "data": [spec.to_dict() for spec in all_specs()]}


# 字面路径先挂：/students/fields 不能被 /students/{row_id} 先匹配掉
router.include_router(student_fields_router)
# 同理：/students/name-conflicts 也不能被 /students/{row_id} 先吃掉
router.include_router(student_reports_router)
# 同理：/attendance/day、/attendance/summary 必须先于 /attendance/{row_id}
router.include_router(attendance_day_router)
# /exams/{id}/sheet、/exams/{id}/report … 必须先于 /exams/{row_id}
router.include_router(exams_router)
# /dorms/tree、/dorms/unassigned 必须先于 /dorm_rooms/{row_id} 之类（同一个字面路径规矩）
router.include_router(dorms_router)

# 静态表：声明写死在注册表里，这里直接生成路由
for _spec in TABLES.values():
    router.include_router(build_router(lambda spec=_spec: spec))

# 导入 / 导出 / 模板下载：不属于某一张表，单独挂载
router.include_router(transfer_router)
router.include_router(export_router)


def register_dynamic_routers(app: FastAPI) -> None:
    """把动态表的路由挂到应用上（在 `create_app` 里调用）。

    传的是 provider 而不是 spec：学生档案的字段定义随时可变，
    路由必须每次请求重新取声明，否则老师加了字段要重启才生效。

    注意 `prefix="/api/v1"`：`build_router` 生成的前缀只有 `/{key}`，
    静态表那条路是靠父级路由器带上前缀的；动态表直接挂在 app 上，必须自己补 ——
    少了它，请求会落到前端静态托管，表现为「GET 404、POST 405」（踩过）。
    """
    for provider in DYNAMIC_TABLES.values():
        app.include_router(build_router(provider), prefix="/api/v1")
