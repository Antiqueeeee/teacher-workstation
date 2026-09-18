"""宿舍分布的读写接口。

**只有两个接口，而且都是只读** —— 房间与床位的增删改全部走通用 CRUD，
因为它们需要的那套校验（床位占用、一人一床、容量不能小于已住人数）写在
`services/dorm_service.py` 的保存前钩子里：新增、编辑、导入、批量四条路径**共用同一份**。

这一点是刻意的：旧应用把「加人」写成三条各不相同的路径（工具栏新增、点空格子、
房间底部「增添住宿生」），每条各自处理容量与床号 —— 于是同一个房间在不同入口下
行为不一致。这里只有一个写入口。

**注册顺序**：`/dorms/tree`、`/dorms/unassigned` 是字面路径，必须挂在
`/{key}/{row_id}` 之前（否则 `tree` 会被当成 id 解析）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.session import db_session
from app.schemas.registry import DORM_BED
from app.services.class_scope import resolve_class_id
from app.services.dorm_duty_service import duty_board
from app.services.dorm_service import room_tree, unassigned_boarders

router = APIRouter(prefix="/dorms", tags=["宿舍分布"])


@router.get("/tree")
def tree(request: Request, session: Session = Depends(db_session)):
    """宿舍分布看板：每间房的容量与床位占用 + 还没分到床位的住宿生。"""
    class_id = resolve_class_id(DORM_BED, request.query_params.get("classId"), session)
    return {"ok": True, "data": room_tree(session, class_id)}


@router.get("/unassigned")
def unassigned(request: Request, session: Session = Depends(db_session)):
    """住宿但还没有床位的学生（旧应用只在卡片视图里显示这个数，列表视图看不到）。"""
    class_id = resolve_class_id(DORM_BED, request.query_params.get("classId"), session)
    return {"ok": True, "data": unassigned_boarders(session, class_id)}


@router.get("/duties")
def duties(request: Request, session: Session = Depends(db_session)):
    """值日看板：按房间分组，每间房列出 7 天各自的安排。

    分组在服务端做 —— 旧应用是前端把整表拉下来分组，记录一多到分页就会缺一块，
    而界面上看不出来。
    """
    class_id = resolve_class_id(DORM_BED, request.query_params.get("classId"), session)
    return {"ok": True, "data": duty_board(session, class_id)}
