"""座位安排的读写接口。

批量操作（随机排位 / 轮换 / 交换 / 回退）必须在服务端一次事务完成，而且要能回退 ——
旧应用这三处都是直接整体替换 `DB.data.seats`（`:10704`），做错了没有退路。

**注册顺序**：`/seats/board` 等字面路径必须挂在 `/{key}/{row_id}` 之前。
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.schemas.registry import SEAT
from app.services.class_scope import resolve_class_id
from app.services.params import as_int
from app.services.seat_service import (
    board,
    clear_seats,
    get_plan,
    randomize,
    restore,
    set_plan,
    shift,
    swap,
)

router = APIRouter(prefix="/seats", tags=["座位安排"])


@router.get("/board")
def get_board(request: Request, session: Session = Depends(get_session)):
    """座位表：行列数、每格是谁、还没排座的学生、以及能不能回退。"""
    class_id = resolve_class_id(SEAT, request.query_params.get("classId"), session)
    return {"ok": True, "data": board(session, class_id)}


@router.put("/plan")
def put_plan(
    request: Request, body: dict = Body(default_factory=dict), session: Session = Depends(get_session)
):
    """改座位表的行列数与排位原则。缩小之前会先检查有没有座位落到格子外面。"""
    class_id = resolve_class_id(SEAT, request.query_params.get("classId") or body.get("classId"), session)
    plan = set_plan(session, class_id, body.get("rows"), body.get("cols"), body.get("rule"))
    return {
        "ok": True,
        "data": {"rows": plan.rows, "cols": plan.cols, "rule": plan.rule},
    }


@router.get("/plan")
def read_plan(request: Request, session: Session = Depends(get_session)):
    class_id = resolve_class_id(SEAT, request.query_params.get("classId"), session)
    plan = get_plan(session, class_id)
    return {"ok": True, "data": {"rows": plan.rows, "cols": plan.cols, "rule": plan.rule}}


@router.post("/randomize")
def post_randomize(
    request: Request, body: dict = Body(default_factory=dict), session: Session = Depends(get_session)
):
    """一键随机排位：保留备注与锁定座位，座位不够时自动加排（并如实报出来）。"""
    class_id = resolve_class_id(SEAT, request.query_params.get("classId") or body.get("classId"), session)
    result = randomize(session, class_id)
    return {"ok": True, "data": {**result, **board(session, class_id)}}


@router.post("/shift")
def post_shift(
    request: Request, body: dict = Body(default_factory=dict), session: Session = Depends(get_session)
):
    """整体轮换（每月换座）：锁定座位不动，其余越界回绕。"""
    class_id = resolve_class_id(SEAT, request.query_params.get("classId") or body.get("classId"), session)
    direction = str(body.get("direction") or "").strip()
    result = shift(session, class_id, direction, body.get("step") or 1)
    return {"ok": True, "data": {**result, **board(session, class_id)}}


@router.post("/swap")
def post_swap(
    request: Request, body: dict = Body(default_factory=dict), session: Session = Depends(get_session)
):
    """把一个座位挪到（或与）目标格交换 —— 拖拽与点选交换共用这一个接口。"""
    class_id = resolve_class_id(SEAT, request.query_params.get("classId") or body.get("classId"), session)
    result = swap(
        session,
        class_id,
        as_int(body.get("seatId"), "seatId"),
        as_int(body.get("row"), "row"),
        as_int(body.get("col"), "col"),
    )
    return {"ok": True, "data": {**result, **board(session, class_id)}}


@router.post("/restore")
def post_restore(
    request: Request, body: dict = Body(default_factory=dict), session: Session = Depends(get_session)
):
    """回退到上一次批量操作之前（只能回退一次）。"""
    class_id = resolve_class_id(SEAT, request.query_params.get("classId") or body.get("classId"), session)
    result = restore(session, class_id)
    return {"ok": True, "data": {**result, **board(session, class_id)}}


@router.post("/clear")
def post_clear(
    request: Request, body: dict = Body(default_factory=dict), session: Session = Depends(get_session)
):
    """清空座位表（座位全删掉，座位表参数留着）。破坏性操作，能回退一次。"""
    class_id = resolve_class_id(SEAT, request.query_params.get("classId") or body.get("classId"), session)
    removed = clear_seats(session, class_id)
    return {"ok": True, "data": {"removed": removed, **board(session, class_id)}}
