/**
 * 座位安排。
 *
 * 页面 = 看板（讲台 + 网格，点选交换/放人）+ 通用列表（座位的逐条增删改、导入导出）。
 *
 * 一键随机排位、整体轮换、交换、回退都在服务端算并一次事务落库
 * （见 backend/app/services/seat_service.py）—— **备注与锁定座位是刻意保护的**：
 * 旧应用随机排位时强制 `note:''`，视力/身高的备注全丢，而且没有锁定与撤销。
 */

import { seatPanel } from '../components/seat-board.js';

export const seatsPageDef = {
  specKey: 'seats',
  group: '班级事务',
  iconName: 'grid',
  panel: seatPanel,
};
