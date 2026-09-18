"""学生档案的**报表类**接口：同名/同学号冲突。

为什么要有它：这个系统里「姓名」是老师习惯的输入，而**姓名不是唯一标识** ——
会议里就点过「有重名」这个现实问题。写入口（监护人、出勤）在遇到重名时会报错
让人确认，但那是**一条一条**发现的：老师得先撞上一次才知道班上重名了。

这个接口把冲突一次列全，学生档案页面顶部据此提示「有 2 组同名、1 组同学号」，
让老师能主动去改（把其中一个改成可区分的写法），而不是每次录数据都被拦一次。

（`02` §2「学生档案」的验收标准：同名与学号冲突**全部进报告**且可人工裁决。）

**注册顺序**：与 `student_fields.py` 一样，必须在通用的 `/students/{row_id}` 之前挂载，
否则 `name-conflicts` 会被当成 id 去解析。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.schemas.registry import get_spec
from app.services.class_scope import resolve_class_id
from app.services.comment_service import comment_draft
from app.services.student_service import archive, identity_conflicts

router = APIRouter(prefix="/students", tags=["学生档案"])


@router.get("/{student_id}/archive")
def student_archive(student_id: int, session: Session = Depends(get_session)):
    """一生一档：一个学生在这套系统里的全部痕迹（各段的数都从所属模块的口径服务取）。"""
    return {"ok": True, "data": archive(session, student_id)}


@router.get("/{student_id}/comment-draft")
def student_comment_draft(student_id: int, session: Session = Depends(get_session)):
    """评语草稿：结构化维度 + 可直接编辑的文本（末尾固定「请人工复核」）。

    用 GET 而不是 POST：它只读、不改任何东西（文档里写的是 POST，但那是排版时的猜测）。
    """
    return {"ok": True, "data": comment_draft(session, student_id)}


@router.get("/name-conflicts")
def name_conflicts(request: Request, session: Session = Depends(get_session)):
    """本班的同名与同学号分组。没有冲突时两个列表都是空的。"""
    spec = get_spec("students")
    class_id = resolve_class_id(spec, request.query_params.get("classId"), session)
    return {"ok": True, "data": identity_conflicts(session, class_id)}
