/**
 * 学科与成绩：课程看板（每门课的班级数/人数/作业提交率/最近一场成绩）+ 课程列表。
 *
 * 课程班级、课程名单、课程成绩各有自己的列表页（能导入导出、手机上按卡片看），
 * 看板是它们的友好入口：进入管理 → 班级与名单 / 作业情况 / 学期成绩。
 * 旧应用把这一整套塞进一个多层嵌套页里，数据既拿不出来也没法导入导出。
 */

import { coursePanel } from '../components/course-board.js';

export const coursesPageDef = {
  specKey: 'courses',
  group: '教学学业',
  iconName: 'book',
  panel: coursePanel,
};
