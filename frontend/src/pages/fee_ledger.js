/**
 * 收支流水：班费的一笔笔进出（方向是显式枚举「收入 / 支出」）。
 *
 * 旧应用把「不是支出」一律当收入 —— 导入时一个错别字就能把一笔开销记成进账，
 * 而班费的余额是拿给家长看的。
 */

export const feeLedgerPageDef = {
  specKey: 'fee_ledger',
  group: '班级事务',
  iconName: 'chart',
};
