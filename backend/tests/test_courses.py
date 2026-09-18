"""学科与成绩的测试。

要害有四个，都是旧应用在这块踩过的坑：

1. **及格线与分析阈值按满分算**（旧应用写死 60 分、150 分上限、80%/40 分三个数，
   150 分制的科目上全错）；
2. **名次同分并列**（旧应用 `forEach((r,i)=>r.rank=i+1)`，换个顺序名次就变）；
3. **课程作业与作业情况是同一份数据**（旧应用 `courses[].homework[].rate` 是手填的
   第二份并行数据），所以提交率、未交名单必须走同一套；
4. **「填名字」的解析不猜**：查不到、重名、跨课程都要报错，而不是挂到别人身上。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.models.class_ import Class
from app.models.course import CourseScore, CourseStudent
from app.models.homework import Homework
from app.models.student import Student


def _class_id(session) -> int:
    return session.scalar(select(Class.id).where(Class.deleted_at.is_(None)).limit(1))


def _student(session, name: str, sno: str) -> Student:
    student = Student(class_id=_class_id(session), name=name, sno=sno, extra={})
    session.add(student)
    session.commit()
    return student


def _course(client, name: str = "数学", **overrides) -> dict:
    payload = {"name": name, "subject": "数学", "hours": 36, "teacher": "王老师"}
    payload.update(overrides)
    response = client.post("/api/v1/courses", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _course_class(client, course_name: str, class_name: str, **overrides) -> dict:
    payload = {"course_name": course_name, "class_name": class_name, "progress": "第一章"}
    payload.update(overrides)
    response = client.post("/api/v1/course_classes", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _score(client, course_name: str, exam: str, student: str, score: float, **overrides):
    payload = {
        "course_name": course_name,
        "exam_name": exam,
        "student_name": student,
        "score": score,
    }
    payload.update(overrides)
    return client.post("/api/v1/course_scores", json=payload)


def _analysis(client, course_id: int, **params) -> dict:
    response = client.get(f"/api/v1/courses/{course_id}/analysis", params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_course_flow_lists_classes_roster_and_scores(client, db_session):
    class_id = _class_id(db_session)
    for index, name in enumerate(("课程甲", "课程乙", "课程丙"), start=1):
        _student(db_session, name, f"C900{index}")
    course = _course(client)
    assert course["class_count"] == 0

    block = _course_class(client, "数学", "我的班级", head_teacher="李老师", rep_phone="13800000000")
    assert block["class_id"] == class_id
    assert block["class_name"] == "我的班级"

    response = client.post(
        f"/api/v1/courses/{course['id']}/students",
        json={"courseClassId": block["id"], "names": "课程甲、课程乙"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "requested": 2,
        "added": 2,
        "addedNames": ["课程甲", "课程乙"],
        "skipped": 0,
    }

    detail = client.get(f"/api/v1/courses/{course['id']}/detail").json()["data"]
    assert detail["course"]["name"] == "数学"
    assert len(detail["classes"]) == 1
    assert detail["classes"][0]["studentCount"] == 2
    assert [row["studentName"] for row in detail["classes"][0]["students"]] == ["课程甲", "课程乙"]
    assert detail["classes"][0]["headTeacher"] == "李老师"

    # 课程名单的通用列表：填的是名字，落库的是 id（界面上不出现 id）
    listed = client.get("/api/v1/course_students").json()["data"]
    assert {row["student_name"] for row in listed} == {"课程甲", "课程乙"}
    assert all(row["course_name"] == "数学" for row in listed)
    assert all(row["class_name"] == "我的班级" for row in listed)


def test_pass_line_is_computed_from_full_marks(client, db_session):
    """及格按**得分率**判定：150 分制考 100 分（66.7%）及格，200 分制考 100 分（50%）不及格。"""
    _student(db_session, "满分甲", "C9101")
    course = _course(client, "语文", subject="语文")
    _course_class(client, "语文", "我的班级")

    # 满分留空 → 按科目词表默认（语文 150）
    first = _score(client, "语文", "第一次月考", "满分甲", 100)
    assert first.status_code == 201, first.text
    assert first.json()["data"]["full_marks"] == 150
    assert first.json()["data"]["passed"] is True
    assert first.json()["data"]["rate"] == 66.7

    # 同场考试的第二条：满分沿用同场已有记录，不必再填
    _student(db_session, "满分乙", "C9102")
    second = _score(client, "语文", "第一次月考", "满分乙", 80)
    assert second.json()["data"]["full_marks"] == 150

    # 手动填 200 分满分：同样 100 分就不及格了（旧应用一律按 60 分比）
    third = _score(client, "语文", "第二次月考", "满分甲", 100, full_marks=200)
    assert third.json()["data"]["passed"] is False
    assert third.json()["data"]["rate"] == 50.0

    analysis = _analysis(client, course["id"])
    assert analysis["passRatio"] == 0.6
    first_exam = next(item for item in analysis["exams"] if item["examName"] == "第一次月考")
    assert first_exam["passCount"] == 1  # 100/150 过线；80/150 只有 53%，不算及格
    assert first_exam["passRate"] == 50.0
    second_exam = next(item for item in analysis["exams"] if item["examName"] == "第二次月考")
    assert second_exam["passCount"] == 0
    assert any("满分" in note for note in second_exam["notes"]) is False


def test_rank_is_shared_on_ties(client, db_session):
    """同分并列（1,1,3）—— 旧应用按数组顺序给名次，换个顺序结果就变。"""
    for index, name in enumerate(("并列甲", "并列乙", "并列丙"), start=1):
        _student(db_session, name, f"C920{index}")
    course = _course(client)
    _course_class(client, "数学", "我的班级")
    for name, value in (("并列甲", 90), ("并列乙", 90), ("并列丙", 80)):
        assert _score(client, "数学", "月考", name, value).status_code == 201

    exam = _analysis(client, course["id"])["exams"][0]
    ranks = {item["studentName"]: (item["rank"], item["tied"]) for item in exam["ranked"]}
    assert ranks == {"并列甲": (1, True), "并列乙": (1, True), "并列丙": (3, False)}
    # 排序按名次，同分之间的先后按姓名（稳定，不随录入顺序变）
    assert [item["rank"] for item in exam["ranked"]] == [1, 1, 3]
    assert exam["avg"] == 86.7 and exam["highest"] == 90 and exam["lowest"] == 80


def test_growth_series_uses_score_rate_and_date_order(client, db_session):
    """生长曲线按**考试日期**排、纵轴是得分率（旧应用按录入顺序、纵轴写死 100）。"""
    _student(db_session, "曲线甲", "C9301")
    course = _course(client)
    _course_class(client, "数学", "我的班级")
    # 故意先录晚的那场：排序必须按日期，不能按录入顺序
    _score(client, "数学", "期末", "曲线甲", 120, exam_date="2026-06-30", full_marks=150)
    _score(client, "数学", "月考", "曲线甲", 90, exam_date="2026-03-15", full_marks=150)

    analysis = _analysis(client, course["id"])
    assert [item["examName"] for item in analysis["exams"]] == ["月考", "期末"]
    series = analysis["series"]
    assert len(series) == 1
    assert [point["label"] for point in series[0]["points"]] == ["月考", "期末"]
    assert [point["value"] for point in series[0]["points"]] == [60.0, 80.0]
    assert series[0]["delta"] == 20.0

    # 只有一场考试时不给曲线（一个点连不成趋势）
    only_one = _course(client, "只有一场", subject="物理")
    _course_class(client, "只有一场", "我的班级")
    _score(client, "只有一场", "月考", "曲线甲", 88, full_marks=100)
    assert _analysis(client, only_one["id"])["series"] == []


def test_course_homework_is_the_same_homework_table(client, db_session):
    """课程作业就是 `homework` 里带 course_id 的行：提交率走同一套口径。"""
    _student(db_session, "作业甲", "C9401")
    _student(db_session, "作业乙", "C9402")
    course = _course(client)
    response = client.post(
        "/api/v1/homework",
        json={
            "date": date.today().isoformat(),
            "subject": "数学",
            "content": "课本 P20 1-5 题",
            "course_name": "数学",
            "total": 2,
            "unsubmitted_names": "作业乙",
        },
    )
    assert response.status_code == 201, response.text
    row = response.json()["data"]
    assert row["course_id"] == course["id"]
    assert row["course_name"] == "数学"
    assert row["rate"] == 50  # 2 人交 1 人 → 50%，与作业页同一份计算

    # 学科与成绩页按课程筛作业，靠的就是 filter.course_id
    filtered = client.get("/api/v1/homework", params={"filter.course_id": course["id"]}).json()
    assert filtered["meta"]["total"] == 1

    overview = client.get("/api/v1/courses/overview").json()["data"]
    card = next(item for item in overview["courses"] if item["id"] == course["id"])
    assert card["homeworkCount"] == 1
    assert card["homeworkRate"] == 50.0
    assert card["classCount"] == 0 and card["studentCount"] == 0

    # 班主任的常规作业不带课程：留空就是「不属于任何课程」
    plain = client.post(
        "/api/v1/homework",
        json={
            "date": date.today().isoformat(),
            "subject": "英语",
            "content": "背单词",
            "total": 2,
        },
    ).json()["data"]
    assert plain["course_id"] is None and plain["course_name"] == ""


def test_unknown_and_ambiguous_names_are_reported_not_guessed(client, db_session):
    _student(db_session, "解析甲", "C9501")
    course = _course(client)
    _course_class(client, "数学", "我的班级")

    # 查无此班：把现有班级列出来（不然老师不知道该填什么）
    bad_class = client.post(
        "/api/v1/course_classes", json={"course_name": "数学", "class_name": "高三(9)班"}
    )
    assert bad_class.status_code == 400
    assert "我的班级" in bad_class.json()["error"]["message"]

    # 查无此课
    bad_course = client.post(
        "/api/v1/course_classes", json={"course_name": "体育", "class_name": "我的班级"}
    )
    assert bad_course.status_code == 400
    assert "请先在「学科与成绩」里新增" in bad_course.json()["error"]["message"]

    # 同一门课同一个班只加一次
    again = client.post(
        "/api/v1/course_classes", json={"course_name": "数学", "class_name": "我的班级"}
    )
    assert again.status_code == 400
    assert "已经加过" in again.json()["error"]["message"]

    # 认不出的学生：整批不写，而不是加进去一半
    block = client.get("/api/v1/course_classes").json()["data"][0]
    bad_names = client.post(
        f"/api/v1/courses/{course['id']}/students",
        json={"courseClassId": block["id"], "names": "解析甲、查无此人"},
    )
    assert bad_names.status_code == 400
    assert "查无此人" in bad_names.json()["error"]["message"]
    assert db_session.scalar(select(CourseStudent).where(CourseStudent.deleted_at.is_(None))) is None

    # 同一个学生加两次：明确报错，而不是撞唯一索引给 500
    ok = client.post(
        f"/api/v1/courses/{course['id']}/students",
        json={"courseClassId": block["id"], "names": "解析甲"},
    )
    assert ok.json()["data"]["added"] == 1
    dup = client.post(
        f"/api/v1/courses/{course['id']}/students",
        json={"courseClassId": block["id"], "names": "解析甲"},
    )
    assert dup.status_code == 200
    assert dup.json()["data"]["added"] == 0 and dup.json()["data"]["skipped"] == 1
    # 逐个新增走的是另一条路：要报错，不能静默跳过
    single_dup = client.post(
        "/api/v1/course_students",
        json={"course_name": "数学", "class_name": "我的班级", "student_name": "解析甲"},
    )
    assert single_dup.status_code == 400
    assert "已经在这门课" in single_dup.json()["error"]["message"]


def test_score_of_student_outside_course_is_rejected(client, db_session):
    """课程只教我的班级：别的班的学生录不进来（要报错，不能挂到别人名下）。"""
    _student(db_session, "本课甲", "C9601")
    _student(db_session, "外班乙", "C9602")
    other = Class(grade="高一", class_no="(1)班", name="")
    db_session.add(other)
    db_session.commit()
    outside = Student(class_id=other.id, name="外班学生", sno="C9603", extra={})
    db_session.add(outside)
    db_session.commit()

    course = _course(client)
    _course_class(client, "数学", "我的班级")
    ok = _score(client, "数学", "月考", "本课甲", 88)
    assert ok.status_code == 201, ok.text

    rejected = _score(client, "数学", "月考", "外班学生", 88)
    assert rejected.status_code == 400
    message = rejected.json()["error"]["message"]
    assert "外班学生" in message and "我的班级" in message

    # 同一场同一个学生只能一条：重复录入要带上现有分数，让人知道该去改哪一条
    dup = _score(client, "数学", "月考", "本课甲", 92)
    assert dup.status_code == 400
    assert "已经录过成绩（88.0 分）" in dup.json()["error"]["message"]
    assert db_session.scalar(
        select(CourseScore).where(CourseScore.course_id == course["id"])
    ) is not None


def test_multi_class_course_and_class_filter(client, db_session):
    """任课教师教多个班：一门课的每个班各录各的成绩，分析能按班过滤。"""
    class_id = _class_id(db_session)
    other = Class(grade="高二", class_no="(4)班", name="")
    db_session.add(other)
    db_session.commit()
    _student(db_session, "一班甲", "C9701")
    second = Student(class_id=other.id, name="四班甲", sno="C9702", extra={})
    db_session.add(second)
    db_session.commit()

    course = _course(client)
    block_a = _course_class(client, "数学", "我的班级")
    block_b = _course_class(client, "数学", "高二(4)班")
    assert block_a["class_id"] == class_id and block_b["class_id"] == other.id

    assert _score(client, "数学", "月考", "一班甲", 90, full_marks=100).status_code == 201
    assert _score(client, "数学", "月考", "四班甲", 60, full_marks=100).status_code == 201

    all_rows = _analysis(client, course["id"])["exams"][0]["ranked"]
    assert [item["className"] for item in all_rows] == ["我的班级", "高二(4)班"]
    first_class = _analysis(client, course["id"], classId=class_id)["exams"][0]
    assert first_class["taken"] == 1
    assert first_class["ranked"][0]["studentName"] == "一班甲"

    overview = client.get("/api/v1/courses/overview").json()["data"]
    card = next(item for item in overview["courses"] if item["id"] == course["id"])
    assert card["classCount"] == 2
    assert card["latestExam"]["taken"] == 2


def test_empty_registry_and_soft_deleted_course(client):
    """空系统：看板不假造数字；删掉的课程不再出现在看板与详情里。"""
    assert client.get("/api/v1/courses/overview").json()["data"] == {
        "courses": [],
        "totals": {"courseCount": 0, "classCount": 0, "homeworkCount": 0, "scoreCount": 0},
    }
    course = _course(client, "临时课程", subject="")
    assert client.delete(f"/api/v1/courses/{course['id']}").status_code == 200
    assert client.get(f"/api/v1/courses/{course['id']}/detail").status_code == 404
    assert client.get("/api/v1/courses/overview").json()["data"]["courses"] == []
    assert client.get("/api/v1/courses/99999/analysis").status_code == 404


def test_score_keeps_course_link_when_homework_and_score_deleted(client, db_session):
    """软删除的成绩不算进统计；恢复后回来 —— 软删除必须有出口。"""
    _student(db_session, "删除甲", "C9801")
    course = _course(client)
    _course_class(client, "数学", "我的班级")
    first = _score(client, "数学", "月考", "删除甲", 90, full_marks=100).json()["data"]
    assert _analysis(client, course["id"])["exams"][0]["taken"] == 1

    assert client.delete(f"/api/v1/course_scores/{first['id']}").status_code == 200
    assert _analysis(client, course["id"])["exams"] == []
    assert client.post(f"/api/v1/course_scores/{first['id']}/restore").status_code == 200
    assert _analysis(client, course["id"])["exams"][0]["taken"] == 1

    # 课程作业同一套：删了就不算，恢复就回来
    homework_response = client.post(
        "/api/v1/homework",
        json={
            "date": date.today().isoformat(),
            "subject": "数学",
            "content": "练习",
            "course_name": "数学",
            "total": 1,
        },
    )
    assert homework_response.status_code == 201, homework_response.text
    homework = homework_response.json()["data"]
    assert client.delete(f"/api/v1/homework/{homework['id']}").status_code == 200
    card = client.get("/api/v1/courses/overview").json()["data"]["courses"][0]
    assert card["homeworkCount"] == 0
    assert db_session.scalar(select(Homework).where(Homework.id == homework["id"])) is not None
