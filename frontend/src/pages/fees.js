/**
 * 班级费用：看板（应收/已收/未缴 + 催缴名单）+ 三个通用列表（收费项目/缴费记录/收支流水）。
 *
 * 金额一律按「元」填、库里存**分**（字段类型 money）—— 浮点算钱会出现
 * `0.30000000000000004` 这种尾数，而班费是要跟家长对账的数。
 */

import { feePanel } from '../components/fee-board.js';

export const feesPageDef = {
  specKey: 'fee_categories',
  group: '班级事务',
  iconName: 'coin',
  panel: feePanel,
};
