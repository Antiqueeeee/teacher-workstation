/**
 * 课程班级：一门课教哪个班（含那个班的班主任、课代表联系方式与课程进度）。
 *
 * 两种进法都对：在「学科与成绩」的课程页里加（课程名已预填，只需填班级名），
 * 或在这里直接批量导入（Excel 里写课程名 + 班级名即可，班级与课程都由后端按名字认）。
 */

export const courseClassesPageDef = {
  specKey: 'course_classes',
  group: '教学学业',
  iconName: 'users',
};
