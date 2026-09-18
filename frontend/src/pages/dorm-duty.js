/**
 * 宿舍值日安排。
 *
 * 页面 = 看板（一间房一张卡，周一到周日各自的安排，点「＋」按天加人）+ 通用列表
 * （逐条增删改、导入导出）。
 *
 * 两处与旧应用不同：房间与值日学生都是**主数据引用**（旧版房间下拉不校验是否存在、
 * 值日人只存姓名，学生一改名就与人对不上）；星期存序号，排序天然正确
 * （旧版按 `indexOf` 排，词表里出现没见过的写法就排最前）。
 */

import { dutyPanel } from '../components/duty-board.js';

export const dormDutyPageDef = {
  specKey: 'dorm_duties',
  group: '班级事务',
  iconName: 'broom',
  panel: dutyPanel,
};
