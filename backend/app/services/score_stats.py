"""成绩统计的唯一口径：总分、名次、及格率、单科统计。

旧应用在这里的算法分散在三处（`classStats` `:12063`、成绩单 `:12777`、
学生趋势 `:12881`），每一处都各自读 `scores` 再自己算一遍，于是：

- **名次按数组顺序给**（`:12047`）：同分的学生排在前面就占前面的名次，
  同一份数据换个顺序算出来的名次都不一样；
- **及格线用「所有考试科目并集满分 × 0.6」**（`:12095`）：某场只考 6 科时，
  及格线仍按 9 科的满分算，全班及格率凭空变低；
- **空值当 0 分**（`num()` `:2665`）：缺考的学生与考 0 分的学生分不出来，
  而且一定会排在最后一名；
- **名次与总分是持久化字段**：改了满分设置（`:13251`）不重算，值就一直是错的。

新口径（**只在这里实现一次**，界面只负责显示）：

- **总分** = 该生**实际有分数**的科目之和。缺考的科目不计入总分，也不当 0 分；
- **得分率** = 总分 / 该生**实际参加的科目满分之和**。跨考试比较只能看得分率 ——
  150 分制的数学与 100 分制的地理直接相加没有意义；
- **及格/优秀**按该生实际参加科目的满分之和判定（60% / 80%），
  所以「缺考数学的学生」不会因为少了一科满分而被判不及格；
- **缺考**与**没录**分开报：前者是「学生没来考」，后者是「老师还没录完」。
  两者都不当 0 分，都不计入平均分；
- **名次**：按总分降序，**同分同名次**（标准竞赛排名：1, 2, 2, 4），`tied` 标记
  告诉界面「并列」。名次不落库，每次现算 —— 改满分、转学生都不会让它过期。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.exam import (
    EXCELLENT_RATIO,
    PASS_RATIO,
    RATE_BANDS,
    Exam,
    ExamSubject,
    Score,
)
from app.models.student import Student
from app.models.vocab import subject_order
from app.services.roster import list_class_students


def rate_band(rate: float | None) -> str:
    """单科评价（作用在得分率上）—— 与旧应用 `:12763` 的四档一致。"""
    if rate is None:
        return "—"
    for threshold, label in RATE_BANDS:
        if rate >= threshold:
            return label
    return "短板科目"


def meets(total: int, full: int, ratio: float) -> bool:
    """总分是否达到满分的某个比例。满分 <= 0 时不算达标（不假装通过）。"""
    return full > 0 and total >= full * ratio


@dataclass
class StudentResult:
    """一个学生在一场考试里的结果。"""

    student_id: int
    student_name: str
    sno: str
    full_map: dict[str, int] = field(default_factory=dict)
    values: dict[str, float] = field(default_factory=dict)  # 有分数的科目
    absent: list[str] = field(default_factory=list)       # 缺考的科目
    missing: list[str] = field(default_factory=list)      # 没录的科目
    rank: int | None = None
    tied: bool = False
    prev_total: float | None = None
    prev_rank: int | None = None

    @property
    def total(self) -> float:
        # 统一到一位小数：分数的存储是浮点，不收敛位数的话「同分」判断会失效
        return round(sum(self.values.values()), 1)

    @property
    def attempted_full(self) -> int:
        """该生实际参加考试的科目满分之和（缺考与没录都不算）。

        直接用「有分数的科目」求和，不在别处再减一遍 —— 那样两个地方会漂。
        """
        return sum(self.full_map.get(subject, 0) for subject in self.values)

    @property
    def score_rate(self) -> float | None:
        """得分率（0–100）。一科都没参加时为 None —— 不是 0%。"""
        attempted = self.attempted_full
        if attempted <= 0:
            return None
        return round(self.total / attempted * 100, 1)

    @property
    def took_part(self) -> bool:
        """参加了至少一科 —— 没参加的人不参与排名与平均分。"""
        return bool(self.values)

    @property
    def passed(self) -> bool:
        return self.took_part and meets(self.total, self.attempted_full, PASS_RATIO)

    @property
    def excellent(self) -> bool:
        return self.took_part and meets(self.total, self.attempted_full, EXCELLENT_RATIO)

    def to_dict(self) -> dict[str, Any]:
        return {
            "studentId": self.student_id,
            "studentName": self.student_name,
            "sno": self.sno,
            "values": self.values,
            "absent": self.absent,
            "missing": self.missing,
            "total": self.total,
            "attemptedFull": self.attempted_full,
            "scoreRate": self.score_rate,
            "rank": self.rank,
            "tied": self.tied,
            "passed": self.passed,
            "excellent": self.excellent,
            "prevTotal": self.prev_total,
            "prevRank": self.prev_rank,
        }


@dataclass
class SubjectStat:
    subject: str
    full_marks: int
    scores: list[float] = field(default_factory=list)
    absent: int = 0
    missing: int = 0
    pass_count: int = 0
    prev_avg: float | None = None

    @property
    def taken(self) -> int:
        return len(self.scores)

    @property
    def avg(self) -> float | None:
        if not self.scores:
            return None
        return round(sum(self.scores) / len(self.scores), 1)

    @property
    def highest(self) -> float | None:
        return max(self.scores) if self.scores else None

    @property
    def lowest(self) -> float | None:
        return min(self.scores) if self.scores else None

    @property
    def rate(self) -> float | None:
        """单科得分率（平均分 / 满分）。没实考的人时显示「—」，不是 0%。"""
        average = self.avg
        if average is None or self.full_marks <= 0:
            return None
        return round(average / self.full_marks * 100, 1)

    @property
    def band(self) -> str:
        return rate_band(self.rate)

    @property
    def pass_rate(self) -> float | None:
        if not self.scores:
            return None
        return round(self.pass_count / len(self.scores) * 100, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "fullMarks": self.full_marks,
            "taken": self.taken,
            "absent": self.absent,
            "missing": self.missing,
            "avg": self.avg,
            "highest": self.highest,
            "lowest": self.lowest,
            "rate": self.rate,
            "band": self.band,
            "passCount": self.pass_count,
            "passRate": self.pass_rate,
            "prevAvg": self.prev_avg,
        }


@dataclass
class ExamReport:
    exam_id: int
    exam_name: str
    exam_date: str
    exam_kind: str
    subjects: list[SubjectStat]
    rows: list[StudentResult]  # 按名次排好，没参加的排最后
    previous: dict[str, Any] | None = None

    @property
    def expected(self) -> int:
        """应考人数 = 本场登记范围内的学生数（在册 + 本场有成绩的历史学生）。"""
        return len(self.rows)

    @property
    def taken(self) -> int:
        return sum(1 for row in self.rows if row.took_part)

    @property
    def absent_students(self) -> int:
        """一科都没考、且被标了缺考的学生数。"""
        return sum(1 for row in self.rows if not row.took_part and row.absent)

    @property
    def unrecorded_students(self) -> int:
        """没有任何分数、也没标缺考的学生数 —— 这场还没录到他。"""
        return sum(1 for row in self.rows if not row.took_part and not row.absent)

    @property
    def totals(self) -> list[float]:
        return [row.total for row in self.rows if row.took_part]

    @property
    def avg_total(self) -> float | None:
        values = self.totals
        return round(sum(values) / len(values), 1) if values else None

    @property
    def full_total(self) -> int:
        """本场考试的满分合计 —— **只算这场考的科目**，不是全科并集。"""
        return sum(item.full_marks for item in self.subjects)

    @property
    def pass_count(self) -> int:
        return sum(1 for row in self.rows if row.passed)

    @property
    def excellent_count(self) -> int:
        return sum(1 for row in self.rows if row.excellent)

    def to_dict(self) -> dict[str, Any]:
        values = self.totals
        return {
            "examId": self.exam_id,
            "examName": self.exam_name,
            "examDate": self.exam_date,
            "examKind": self.exam_kind,
            "expected": self.expected,
            "taken": self.taken,
            "absentStudents": self.absent_students,
            "unrecordedStudents": self.unrecorded_students,
            "fullTotal": self.full_total,
            "avgTotal": self.avg_total,
            "highestTotal": max(values) if values else None,
            "lowestTotal": min(values) if values else None,
            "passCount": self.pass_count,
            "excellentCount": self.excellent_count,
            "passRate": _pct(self.pass_count, self.taken),
            "excellentRate": _pct(self.excellent_count, self.taken),
            "subjects": [item.to_dict() for item in self.subjects],
            "rows": [row.to_dict() for row in self.rows],
            "previous": self.previous,
        }


def _pct(count: int, total: int) -> float | None:
    if not total:
        return None
    return round(count / total * 100, 1)


def exam_subject_map(session: Session, exam_id: int) -> dict[str, int]:
    """这场考试的科目 → 满分。**「本场满分」的唯一来源。**"""
    rows = session.scalars(select(ExamSubject).where(ExamSubject.exam_id == exam_id))
    return {row.subject: row.full_marks for row in rows}


def ordered_subjects(session: Session, exam_id: int) -> list[str]:
    """这场考试的科目，按词表顺序排（录入表与报表的列顺序必须一致）。"""
    return sorted(exam_subject_map(session, exam_id), key=subject_order)


def previous_exam(session: Session, exam: Exam) -> Exam | None:
    """同一班级里、日期早于本场的上一场考试。

    判定用 `(date, id)` 双键：同一天有两场考试时顺序仍然确定，不会因为
    「全表取用顺序」而随机 —— 旧应用直接按存储顺序取（`:8166`），
    把「最近一次考试」取成了更早的那一场，评语里的进步/退步方向整个反过来。
    """
    return session.scalars(
        select(Exam)
        .where(
            Exam.deleted_at.is_(None),
            Exam.class_id == exam.class_id,
            Exam.id != exam.id,
            (Exam.date < exam.date) | ((Exam.date == exam.date) & (Exam.id < exam.id)),
        )
        .order_by(Exam.date.desc(), Exam.id.desc())
        .limit(1)
    ).first()


def _roster(session: Session, exam: Exam) -> list[Student]:
    """本场应考的学生：当前在册学生 ∪ 本场已有成绩的学生。

    后半句是为了历史考卷：学生转学走了（软删除），他在这场的成绩仍然要能看得到，
    否则「上次考了第 3 名」会在学生转出的那一刻凭空消失。
    """
    roster = list_class_students(session, exam.class_id)
    known = {student.id for student in roster}
    for student_id in session.scalars(
        select(Score.student_id).where(Score.exam_id == exam.id).distinct()
    ):
        if student_id in known:
            continue
        student = session.get(Student, student_id)
        if student is not None:
            roster.append(student)
            known.add(student_id)
    return roster


def build_report(session: Session, exam: Exam, *, include_previous: bool = True) -> ExamReport:
    """算出一场考试的完整报表。界面、导出、首页卡片都读它。"""
    full_map = exam_subject_map(session, exam.id)
    subjects = [
        SubjectStat(subject=subject, full_marks=full_map[subject])
        for subject in sorted(full_map, key=subject_order)
    ]
    subject_index = {item.subject: item for item in subjects}

    rows: list[StudentResult] = []
    for student in _roster(session, exam):
        rows.append(
            StudentResult(
                student_id=student.id,
                student_name=student.name,
                sno=student.sno,
                full_map=full_map,
            )
        )
    by_student = {row.student_id: row for row in rows}

    for score in session.scalars(select(Score).where(Score.exam_id == exam.id)):
        result = by_student.get(score.student_id)
        stat = subject_index.get(score.subject)
        if result is None or stat is None:
            # 这种行**通过接口造不出来**：`set_subjects` 拒绝移出已有成绩的科目，
            # `save_cells` 拒绝不在本场科目里的分数。这里是防手工改库的兜底 ——
            # 统计时忽略，不静默把它算进某个学生或某科
            continue
        if score.absent:
            result.absent.append(score.subject)
            stat.absent += 1
        elif score.value is not None:
            result.values[score.subject] = score.value
            stat.scores.append(score.value)
            if meets(score.value, stat.full_marks, PASS_RATIO):
                stat.pass_count += 1

    for result in rows:
        # 库里没有那一行，对老师来说同样是「还没录」——报表要如实说出来
        result.missing = [
            subject
            for subject in full_map
            if subject not in result.values and subject not in result.absent
        ]
        result.absent.sort(key=subject_order)
        result.missing.sort(key=subject_order)
        for subject in result.missing:
            subject_index[subject].missing += 1

    for subject in full_map:
        subject_index[subject].scores.sort()

    _apply_ranks(rows)

    previous = previous_exam(session, exam) if include_previous else None
    if previous is not None:
        _attach_previous(session, rows, subjects, previous)

    ordered = sorted(
        rows,
        # 没参加的人排最后；同分时按姓名兜底，保证每次打开顺序一致
        key=lambda row: (0 if row.rank is not None else 1, row.rank or 0, row.student_name),
    )

    return ExamReport(
        exam_id=exam.id,
        exam_name=exam.name,
        exam_date=exam.date.isoformat(),
        exam_kind=exam.kind,
        subjects=subjects,
        rows=ordered,
        previous=(
            {
                "examId": previous.id,
                "examName": previous.name,
                "examDate": previous.date.isoformat(),
            }
            if previous is not None
            else None
        ),
    )


def _apply_ranks(rows: list[StudentResult]) -> None:
    """标准竞赛排名：1, 2, 2, 4。同分并列，下一个名次跳过被占用的位次。

    旧应用是 `forEach((r,i)=> r.rank = i+1)`（`:12049`）：同分的学生按数组顺序
    拿到不同名次，同一份数据换个顺序名次就变了。
    """
    ranked = sorted((row for row in rows if row.took_part), key=lambda row: -row.total)
    rank = 0
    previous_total: float | None = None
    for index, row in enumerate(ranked, start=1):
        if previous_total is None or row.total < previous_total:
            rank = index  # 分数降了才占新名次，同分沿用上一个名次
            previous_total = row.total
        row.rank = rank

    counts: dict[int, int] = {}
    for row in ranked:
        counts[row.rank] = counts.get(row.rank, 0) + 1
    for row in ranked:
        row.tied = counts[row.rank] > 1


def _attach_previous(
    session: Session,
    rows: list[StudentResult],
    subjects: list[SubjectStat],
    previous: Exam,
) -> None:
    """与上一场对比：总分差、名次升降、各科平均进退。

    用同一个 `build_report` 算上一场（`include_previous=False` 防止无限回溯）——
    「较上次」与「本次」的口径必须完全一致，否则对比本身没有意义。
    """
    prev_report = build_report(session, previous, include_previous=False)
    prev_by_student = {row.student_id: row for row in prev_report.rows}
    for row in rows:
        match = prev_by_student.get(row.student_id)
        if match is not None and match.took_part:
            row.prev_total = match.total
            row.prev_rank = match.rank

    prev_by_subject = {item.subject: item for item in prev_report.subjects}
    for item in subjects:
        match = prev_by_subject.get(item.subject)
        if match is not None and match.avg is not None:
            item.prev_avg = match.avg


def subject_sheet(session: Session, exam: Exam) -> list[dict[str, Any]]:
    """录入表要用的列：这场考试的科目与满分。"""
    full_map = exam_subject_map(session, exam.id)
    return [
        {"subject": subject, "fullMarks": full_map[subject]}
        for subject in sorted(full_map, key=subject_order)
    ]
