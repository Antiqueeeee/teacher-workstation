"""导入接口：文件 → 可编辑预览 → 确认后单事务写入；以及导入模板下载。

路径（见 `docs/改造方案/03` §5.2）：
    GET  /api/v1/transfer/template/{table}.xlsx   下载导入模板（表头 + 示例 + 字段说明批注）
    POST /api/v1/transfer/import?table=…          上传文件，返回**预览**，不写库
    POST /api/v1/transfer/import/commit?table=…   提交确认后的行，单事务写入

为什么预览不落库、也不发令牌：见 `services/import_service.py` 的模块说明。
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, File, Response, UploadFile
from sqlalchemy.orm import Session

from app.api.errors import TABLE_NOT_FOUND, ApiError
from app.api.session import db_session
from app.schemas.registry import TableSpec, get_spec
from app.services import import_service, table_io
from app.services.class_scope import resolve_class_id

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

router = APIRouter(prefix="/transfer", tags=["导入导出"])


def _spec(table: str) -> TableSpec:
    spec = get_spec(table)
    if spec is None:
        raise ApiError(TABLE_NOT_FOUND, f"没有名为「{table}」的表", status=404)
    return spec


@router.get("/template/{table}.xlsx")
def download_template(table: str):
    spec = _spec(table)
    name = f"{spec.title}-导入模板.xlsx"
    return Response(
        content=table_io.build_template(spec),
        media_type=XLSX_MIME,
        headers={
            # 老浏览器看 filename，新浏览器看 filename*（中文名必须走 RFC 5987）
            "Content-Disposition": f"attachment; filename=import-template.xlsx; filename*=UTF-8''{quote(name)}"
        },
    )


@router.post("/import")
async def import_preview(table: str, file: UploadFile = File(...)):
    spec = _spec(table)
    content = await file.read()
    try:
        data = import_service.preview(spec, file.filename or "", content)
    except import_service.ImportFailed as exc:
        raise ApiError(exc.code, exc.message) from None
    return {"ok": True, "data": data}


@router.post("/import/commit")
def import_commit(
    table: str,
    body: dict = Body(...),
    session: Session = Depends(db_session),
):
    spec = _spec(table)
    rows = body.get("rows") or []
    try:
        class_id = resolve_class_id(spec, body.get("classId"), session)
        data = import_service.commit(spec, session, rows, class_id)
    except import_service.ImportFailed as exc:
        # 抛出去后，会话收尾时会回滚，库里不会留下半份导入结果
        raise ApiError(exc.code, exc.message) from None
    return {"ok": True, "data": data}
