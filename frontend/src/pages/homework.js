/**
 * 作业情况。
 *
 * 提交率不用人工算：填「未交名单」，后端按「应交人数 − 未交人数」算出提交率，
 * 列表、导出、导入读的是同一个值（见 backend/app/services/homework_service.py）。
 * 「应交人数」留空时按当时全班人数快照 —— 之后学生转入转出不会改写历史记录。
 */

export const homeworkPageDef = { specKey: 'homework', group: '教学学业', iconName: 'pencil' };
