"""全部模型集中导出。

**新增模型必须在这里 import**，否则 Alembic 自动生成迁移时看不到它。
"""

from app.models.app_state import AppState
from app.models.attendance import Attendance
from app.models.class_ import Class
from app.models.guardian import Guardian
from app.models.homework import Homework, HomeworkUnsubmitted
from app.models.rule import Rule
from app.models.student import Student, StudentFieldDef
from app.models.template import Template
from app.models.todo import Todo

__all__ = [
    "AppState",
    "Attendance",
    "Class",
    "Guardian",
    "Homework",
    "HomeworkUnsubmitted",
    "Rule",
    "Student",
    "StudentFieldDef",
    "Template",
    "Todo",
]
