/**
 * 缴费记录：某个学生在某个收费项目上的应缴与实缴。
 *
 * 金额按「元」填、库里存**分**（字段类型 money）—— 浮点算钱会出现小数尾数，
 * 而这是要跟家长对账的数。状态（已缴/部分/未缴/免缴）是**推导值**，
 * 不落库、也不让人填（见 services/fee_service.py:status_of）。
 */

export const feeRecordsPageDef = {
  specKey: 'fee_records',
  group: '班级事务',
  iconName: 'coin',
};
