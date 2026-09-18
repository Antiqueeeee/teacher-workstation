"""全部模型集中导出。

**新增模型必须在这里 import**，否则 Alembic 自动生成迁移时看不到它。
"""

from app.models.app_state import AppState
from app.models.attendance import Attendance
from app.models.class_ import Class
from app.models.classroom import Cadre, DutyGroup, DutyMember, YouthMember
from app.models.communication import (
    ClassActivity,
    ClassEvent,
    Conflict,
    ConflictParty,
    Meeting,
    Talk,
    Visit,
)
from app.models.contact import ContactLog
from app.models.dorm import DormBed, DormDuty, DormRoom
from app.models.discipline import Discipline
from app.models.exam import Exam, ExamSubject, Score
from app.models.guardian import Guardian
from app.models.homework import Homework, HomeworkUnsubmitted
from app.models.media import Media
from app.models.rule import Rule
from app.models.seat import Seat, SeatPlan
from app.models.student import Student, StudentFieldDef
from app.models.template import Template
from app.models.todo import Todo
from app.models.welfare import Grant, HealthRecord

__all__ = [
    "AppState",
    "Attendance",
    "Class",
    "Cadre",
    "ContactLog",
    "Visit",
    "Talk",
    "Meeting",
    "ConflictParty",
    "Conflict",
    "ClassEvent",
    "ClassActivity",
    "Discipline",
    "DormBed",
    "DormDuty",
    "DormRoom",
    "DutyGroup",
    "DutyMember",
    "Exam",
    "ExamSubject",
    "Grant",
    "Guardian",
    "HealthRecord",
    "Homework",
    "HomeworkUnsubmitted",
    "Media",
    "Rule",
    "Seat",
    "SeatPlan",
    "Score",
    "Student",
    "StudentFieldDef",
    "Template",
    "Todo",
    "YouthMember",
]
