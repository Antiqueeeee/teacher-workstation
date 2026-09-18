"""导出接口。

`GET /api/v1/transfer/export/{table}.xlsx` —— **导出「当前筛选结果」**，不是全表。
筛选由 `services/table_query.py` 提供，与列表接口是同一份实现，
所以屏幕上看到的和导出的必然一致。
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.errors import TABLE_NOT_FOUND, ApiError
from app.db.engine import get_session
from app.schemas.registry import TableSpec, get_spec
from app.services import table_io
from app.services.table_query import export_rows

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_EXPORT_ROWS = 20000  # 防止一次导出把内存和 Excel 都拖垮

router = APIRouter(prefix="/transfer", tags=["导入导出"])


def _spec(table: str) -> TableSpec:
    spec = get_spec(table)
    if spec is None:
        raise ApiError(TABLE_NOT_FOUND, f"没有名为「{table}」的表", status=404)
    return spec


@router.get("/export/{table}.xlsx")
def export_xlsx(table: str, request: Request, session: Session = Depends(get_session)):
    spec = _spec(table)
    rows = export_rows(session, spec, request.query_params, MAX_EXPORT_ROWS)
    if len(rows) == MAX_EXPORT_ROWS:
        raise ApiError(
            "EXPORT_TOO_LARGE",
            f"命中的记录超过 {MAX_EXPORT_ROWS} 条，请先用筛选缩小范围再导出",
            status=409,
        )
    name = f"{spec.title}.xlsx"
    return Response(
        content=table_io.build_export(spec, rows),
        media_type=XLSX_MIME,
        headers={
            "Content-Disposition": f"attachment; filename={spec.key}.xlsx; filename*=UTF-8''{quote(name)}"
        },
    )
