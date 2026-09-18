"""学科与成绩：取记录、名称解析钩子、批量加名单。

这个模块里有两件**只能有一处实现**的事：

1. **「老师填名字，程序要 id」**（旧应用存的是 `sno` 字符串，历史数据里还有数字型）：
   课程名 → 课程、班级名 → 班级、学生姓名 → 学生。与作业的未交名单、监护人等
   共用 `roster.find_student` / `class_scope.find_class` 的同一套「查不到、重名都不猜」；
2. **成绩口径**（得分率、及格）：在 `models/course.py`（模型属性要用，而 models
   不能 import services）—— 及格线不再写死 60 分（旧应用 `:14797` 那个数在 150 分制
   的科目上全错），改成按满分算的得分率。

**统计与看板不在这里**：`services/course_stats.py`（各场考试统计、分析文字、
成绩生长曲线、课程卡片）。那边的分子分母都来自这里写下的数据。
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, NOT_FOUND, ApiError
from app.models.class_ import Class
from app.models.course import Course, CourseClass, CourseScore, CourseStudent
from app.models.vocab import DEFAULT_FULL_MARKS as SUBJECT_FULL_MARKS
from app.services.class_scope import class_label, find_class
from app.services.roster import find_student, split_names

__all__ = [
    "add_students",
    "apply_course_class",
    "apply_course_score",
    "apply_course_student",
    "class_labels",
    "course_class_ids",
    "default_full_marks",
    "find_course",
    "fine_course_class",
    "get_course",
    "get_course_class",
]

# --------------------------------------------------------------- 取记录


def _as_id(raw: Any, label: str) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError(INVALID_VALUE, f"{label}的编号不是数字：{raw!r}", detail={"value": raw}) from None


def get_course(session: Session, course_id: Any) -> Course:
    row = session.get(Course, _as_id(course_id, "课程"))
    if row is None or row.deleted_at is not None:
        raise ApiError(NOT_FOUND, "这门课程不存在，可能已被删除", status=404, detail={"id": course_id})
    return row


def get_course_class(session: Session, course_class_id: Any) -> CourseClass:
    row = session.get(CourseClass, _as_id(course_class_id, "课程班级"))
    if row is None or row.deleted_at is not None:
        raise ApiError(NOT_FOUND, "这个课程班级不存在，可能已被删除", status=404)
    return row


def class_labels(session: Session) -> dict[int, str]:
    """班级展示名一览（一次查完）—— 成绩行要显示是哪个班的，逐行查就是 N+1。"""
    return {row.id: class_label(row) for row in session.scalars(select(Class))}


def find_course(session: Session, name: str) -> Course:
    """按课程名找课程。**重名不猜** —— 两门都叫「数学」时请老师先把名字改开。"""
    wanted = str(name or "").strip()
    if not wanted:
        raise ApiError(INVALID_VALUE, "要填课程名称", detail={"field": "course_name"})
    matched = list(
        session.scalars(select(Course).where(Course.deleted_at.is_(None), Course.name == wanted))
    )
    if not matched:
        raise ApiError(
            INVALID_VALUE,
            f"没有叫「{wanted}」的课程，请先在「学科与成绩」里新增这门课",
            detail={"field": "course_name", "value": wanted},
        )
    if len(matched) > 1:
        raise ApiError(
            INVALID_VALUE,
            f"有 {len(matched)} 门课都叫「{wanted}」，系统分不清是哪一门。"
            "请把它们改成可区分的名字（如「数学·上学期」）。",
            detail={"field": "course_name", "value": wanted},
        )
    return matched[0]


def course_class_ids(session: Session, course_id: int) -> list[int]:
    """这门课教的所有班（未删除）—— 学生与成绩的归属判定要用。"""
    return list(
        session.scalars(
            select(CourseClass.class_id).where(
                CourseClass.course_id == course_id, CourseClass.deleted_at.is_(None)
            )
        )
    )


def fine_course_class(session: Session, course_id: int, class_id: int) -> CourseClass:
    """这门课在这个班上的班级块；没有就报一句能照着做的话。"""
    row = session.scalars(
        select(CourseClass).where(
            CourseClass.course_id == course_id,
            CourseClass.class_id == class_id,
            CourseClass.deleted_at.is_(None),
        )
    ).first()
    if row is None:
        cls = session.get(Class, class_id)
        raise ApiError(
            INVALID_VALUE,
            f"这门课还没有加「{class_label(cls) if cls else class_id}」这个班，"
            "请先在「学科与成绩」的课程页里把它加进班级。",
            detail={"class_id": class_id},
        )
    return row


# --------------------------------------------------------------- 保存钩子


def apply_course_class(values: dict[str, Any], session: Session, row: Any = None) -> None:
    """课程班级：课程名 → 课程；班级名 → 班级；并把展示名统一成库里那一个。

    与「学生姓名」同一套做法：`class_name` 既是输入、也是落库的**快照名**
    （`class_label`），所以界面上不必出现班级 id。**更新时没动班级就不重新解析** ——
    班级事后改了名，重解析会把一次「改进度」误判成「查无此班」。
    """
    course = _resolve_course(values, session, row)
    values["course_id"] = course.id

    if "class_name" not in values:
        # 更新时没动班级：不重新解析名字（班级可能已改名），但要挡住「改到已加过的班」
        if row is not None:
            _reject_duplicate(
                session,
                CourseClass,
                [CourseClass.course_id == course.id, CourseClass.class_id == row.class_id],
                row,
                "这门课已经加过这个班了",
            )
        return

    text = str(values.get("class_name") or "").strip()
    found, problem = find_class(session, text)
    if problem is not None:
        raise ApiError(INVALID_VALUE, problem, detail={"field": "class_name", "value": text})
    _reject_duplicate(
        session,
        CourseClass,
        [CourseClass.course_id == course.id, CourseClass.class_id == found.id],
        row,
        f"「{course.name}」已经加过「{class_label(found)}」这个班了",
    )
    values["class_id"] = found.id
    values["class_name"] = class_label(found)


def apply_course_student(values: dict[str, Any], session: Session, row: Any = None) -> None:
    """课程名单：课程名 + 班级名 → 班级块；学生姓名 → `student_id`。

    三门「名称 → id」都走同一批解析器（`find_course` / `find_class` / `find_student`），
    任何一个认不出来就整条不写 —— 猜错的后果是把学生的成绩挂到别人身上，且不会报错。
    """
    course = _resolve_course(values, session, row)
    block = _resolve_block(session, course, values, row)
    values["course_class_id"] = block.id

    name = _student_name(values, row)
    student, problem, _kind = find_student(session, name=name, class_id=block.class_id, label="学生")
    if problem is not None:
        raise ApiError(INVALID_VALUE, problem, detail={"field": "student_name", "value": name})
    _reject_duplicate(
        session,
        CourseStudent,
        [CourseStudent.course_class_id == block.id, CourseStudent.student_id == student.id],
        row,
        f"「{student.name}」已经在这门课这个班的名单里了",
    )
    values["student_id"] = student.id
    values["student_name"] = student.name
    values["class_id"] = block.class_id


def apply_course_score(values: dict[str, Any], session: Session, row: Any = None) -> None:
    """课程成绩：课程名 → 课程；学生姓名 → 学生（并据此定班级）；满分按同场考试/科目给默认。

    学生必须**在课程的某个班里**：课程可能教 6 个班，学生属于哪个班就记在哪个班上。
    不要求他先在「班级与名单」里 —— 任课教师常常先录成绩、后整理名单
    （旧应用也是这个顺序）；但**跨课程的学生一定挂不上**，这个限制必须报出来。
    """
    course = _resolve_course(values, session, row)
    values["course_id"] = course.id

    name = _student_name(values, row)
    class_ids = course_class_ids(session, course.id)
    student, problem, kind = find_student(session, name=name, class_ids=class_ids, label="学生")
    if problem is not None:
        labels = class_labels(session)
        taught = "、".join(labels[cid] for cid in class_ids if cid in labels) or "（还没加过班级）"
        # 人建了档、只是不在这门课的班里时要说准：`find_student` 的通用话术是
        # 「学生档案里没有叫 X 的学生」，读起来像「没建档」（评审点过这一处）
        message = (
            f"「{name}」不在这门课教的班里（这门课教的班：{taught}）"
            if kind == "missing" and class_ids
            else f"{problem}。这门课教的班：{taught}"
        )
        raise ApiError(INVALID_VALUE, message, detail={"field": "student_name", "value": name})
    values["student_id"] = student.id
    values["student_name"] = student.name
    values["class_id"] = student.class_id
    fine_course_class(session, course.id, student.class_id)  # 没加这个班就当场报出来

    exam_name = str(values.get("exam_name") or getattr(row, "exam_name", "") or "").strip()
    if exam_name:
        # 同一场考试同一个学生只能有一条：重复录入要报出来**并带上现在这条的值**，
        # 否则老师会以为是「又加了一条」，而库里其实只有一条（或者撞唯一索引报 500）
        existing = session.scalars(
            select(CourseScore).where(
                CourseScore.course_id == course.id,
                CourseScore.exam_name == exam_name,
                CourseScore.student_id == student.id,
                CourseScore.deleted_at.is_(None),
            )
        ).first()
        if existing is not None and (row is None or existing.id != row.id):
            raise ApiError(
                INVALID_VALUE,
                f"「{student.name}」的「{exam_name}」已经录过成绩（{existing.score} 分）了，"
                "要改分请到列表里编辑那一条。",
                detail={"field": "exam_name", "value": exam_name},
            )

    if values.get("full_marks") in (None, ""):
        values["full_marks"] = default_full_marks(session, course, exam_name)
    if values.get("exam_date") in (None, ""):
        values["exam_date"] = date.today()


def _reject_duplicate(
    session: Session, model: Any, conditions: list, row: Any, message: str
) -> None:
    """已经有了同一条就明确报错 —— 不让数据库的部分唯一索引先炸成 500。

    **报错而不是静默跳过**：静默跳过会让老师以为「加上了」（旧应用的嵌套数组里
    同一个学生能被加进去好几次，正是这种没人发现的不一致）。
    """
    stmt = select(model.id).where(model.deleted_at.is_(None), *conditions)
    if row is not None and getattr(row, "id", None) is not None:
        stmt = stmt.where(model.id != row.id)
    if session.scalars(stmt.limit(1)).first() is not None:
        raise ApiError(INVALID_VALUE, message)


def default_full_marks(session: Session, course: Course, exam_name: str) -> int:
    """这场考试的满分：同场已有记录 → 科目词表默认（语数英 150，其余 100）→ 100。

    旧应用把满分写死在表单上限里（150），150 分制以外的科目没地方填。
    """
    if exam_name:
        existing = list(
            session.scalars(
                select(CourseScore.full_marks)
                .where(
                    CourseScore.course_id == course.id,
                    CourseScore.exam_name == exam_name,
                    CourseScore.deleted_at.is_(None),
                )
                .limit(50)
            )
        )
        if existing:
            # 取出现次数最多的那个（同场偶有个别录错的满分，不该带偏后面的默认值）
            return Counter(existing).most_common(1)[0][0]
    return int(SUBJECT_FULL_MARKS.get(course.subject, 100))


def _student_name(values: dict[str, Any], row: Any) -> str:
    if "student_name" not in values and row is None:
        raise ApiError(INVALID_VALUE, "必须填写学生姓名", detail={"field": "student_name"})
    raw = values.get("student_name")
    if raw is None:
        raw = getattr(row, "student_name", "")
    return str(raw or "").strip()


def _resolve_course(values: dict[str, Any], session: Session, row: Any) -> Course:
    """课程：提交体里有 `course_name` 就按名字找；否则用这条记录原来挂的课程。

    `course_name` 是**虚拟输入字段**（模型上是只读属性），所以必须在这里 pop 掉，
    否则 `apply()` 会拿它去 setattr（在只读属性上直接抛 `has no setter`）。
    """
    if "course_name" in values:
        return find_course(session, str(values.pop("course_name") or ""))
    if row is not None:
        current = getattr(row, "course_id", None)
        if current:
            return get_course(session, current)
        parent = getattr(row, "course_class", None)
        if parent is not None:
            return get_course(session, parent.course_id)
    raise ApiError(INVALID_VALUE, "必须填写课程名称", detail={"field": "course_name"})


def _resolve_block(
    session: Session, course: Course, values: dict[str, Any], row: Any
) -> CourseClass:
    """班级块：提交体里有 `class_name` 就按名字找班级；否则沿用这条记录原来的班级块。"""
    if "class_name" in values:
        text = str(values.pop("class_name") or "").strip()
        found, problem = find_class(session, text)
        if problem is not None:
            raise ApiError(INVALID_VALUE, problem, detail={"field": "class_name", "value": text})
        return fine_course_class(session, course.id, found.id)
    if row is not None:
        return get_course_class(session, row.course_class_id)
    raise ApiError(INVALID_VALUE, "必须填写班级名称", detail={"field": "class_name"})


# --------------------------------------------------------------- 批量加学生


def add_students(session: Session, block: CourseClass, text: str) -> dict[str, Any]:
    """把一串「张三、李四」加进这个课程班级的名单。

    与作业的未交名单同一条规矩：**认不出的人名整批不写**，把问题说清楚让人改，
    而不是猜着挂上去（旧应用存的是学号字符串，猜错了永远对不上）。
    已经在名单里的人不重复加，但会如实报出跳过了几个。
    """
    names = split_names(text)
    if not names:
        raise ApiError(INVALID_VALUE, "要填学生姓名（可一次填多个，用顿号分隔）", detail={"field": "names"})

    students = []
    problems: list[str] = []
    for name in names:
        student, problem, _kind = find_student(
            session, name=name, class_id=block.class_id, label="学生"
        )
        if problem is not None:
            problems.append(problem)
        else:
            students.append(student)
    if problems:
        raise ApiError(
            INVALID_VALUE, "名单里有认不出的学生：" + "；".join(problems), detail={"field": "names"}
        )

    existing = {
        row.student_id
        for row in session.scalars(
            select(CourseStudent).where(
                CourseStudent.course_class_id == block.id, CourseStudent.deleted_at.is_(None)
            )
        )
    }
    added: list[str] = []
    for student in students:
        if student.id in existing:
            continue
        session.add(
            CourseStudent(
                course_class_id=block.id,
                class_id=block.class_id,
                student_id=student.id,
                student_name=student.name,
            )
        )
        existing.add(student.id)
        added.append(student.name)
    session.flush()
    return {
        "requested": len(names),
        "added": len(added),
        "addedNames": added,
        "skipped": len(students) - len(added),
    }
