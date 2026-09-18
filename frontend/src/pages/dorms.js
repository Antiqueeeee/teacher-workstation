/**
 * 宿舍分布。
 *
 * 页面 = 看板（一间房一张卡，点格子加人/改人/改容量）+ 通用列表（房间的管理：
 * 新增、编辑、删除、导入、导出）。
 *
 * 房间与床位是两张表：**这个页面的列表管房间**（楼栋/房号/容量），
 * 床位在卡片上看 —— 因为老师心里的单位是「这间房住着谁、还剩几个空位」，
 * 不是「第 37 条床位记录」。床位表本身也注册成了表（`dorm_beds`），
 * 所以导入导出、批量、单条编辑那套照样能用。
 */

import { dormPanel } from '../components/dorm-board.js';

export const dormsPageDef = {
  specKey: 'dorm_rooms',
  group: '班级事务',
  iconName: 'building',
  panel: dormPanel,
};
