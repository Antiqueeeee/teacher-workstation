/**
 * 课程表：一周网格（星期 × 节次）+ 通用列表（逐格增删改、导入导出）。
 *
 * 网格是「看」的视角：一眼看清哪天哪节有课、谁上、在哪上。
 * 改课在列表里做 —— 那里有导入导出与软删除找回，能力比格子里的弹窗多。
 */

import { weekGridPanel } from '../components/week-grid.js';

export const schedulePageDef = {
  specKey: 'schedule_slots',
  group: '教学学业',
  iconName: 'calendar',
  panel: weekGridPanel,
};
