/**
 * 课程名单：这门课在这个班上有哪些学生（成绩归属就是按它来的）。
 *
 * 界面填的是课程名 + 班级名 + 学生姓名（后端解析成 id，重名会报错）；
 * Excel 导入同样是这三列。批量加人在「学科与成绩」的课程页里（按姓名一次加一批）。
 */

export const courseStudentsPageDef = {
  specKey: 'course_students',
  group: '教学学业',
  iconName: 'list',
};
