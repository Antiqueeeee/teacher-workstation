/**
 * 作业情况。
 *
 * 提交率不用人工算：填「未交名单」，后端按「应交人数 − 未交人数」算出提交率，
 * 列表、导出、导入读的是同一个值（见 backend/app/services/homework_service.py）。
 * 「应交人数」留空时按当时全班人数快照 —— 之后学生转入转出不会改写历史记录。
 *
 * 列表多一列「按名单算」：手工覆盖（提交率模式 = 手工）时，它与生效的「提交率」
 * 并排显示，差得远就说明手工值有问题。页面上还有一条提醒列出所有对不上的记录 ——
 * 否则「同一个提交率两个来源」在界面上完全看不出来。
 */

import { api } from '../core/api.js';
import { esc } from '../core/dom.js';
import { DASH } from '../core/format.js';
import { store } from '../core/store.js';

const HOMEWORK_PAGE_SIZE = 100;

function rate(value) {
  return value === null || value === undefined ? DASH : `${value}%`;
}

/** 手工覆盖的值与按名单算的值对不上时的提醒条。没有不一致就不显示（不制造噪声）。 */
const panel = {
  async html() {
    try {
      const list = await api.list('homework', {
        pageSize: HOMEWORK_PAGE_SIZE,
        sort: 'date',
        dir: 'desc',
        classId: store.currentClassId,
      });
      const off = list.rows.filter(
        (row) => row.rate_mode === '手工' && row.rate !== row.rate_auto,
      );
      if (!off.length) return '';
      const items = off
        .slice(0, 6)
        .map(
          (row) =>
            `<li>${esc(row.date)} ${esc(row.subject)} ${esc(row.content || '')}
              —— 手工填 ${rate(row.rate)}，按未交名单算是 ${rate(row.rate_auto)}</li>`,
        )
        .join('');
      return `<div class="board">
        <div class="board-head"><span class="board-title">手工填的提交率与名单对不上</span>
          <span class="muted">共 ${off.length} 条</span></div>
        <ul class="plain-list">${items}</ul>
        ${off.length > 6 ? '<div class="muted">只列了前 6 条，导出可以看到全部。</div>' : ''}
        <div class="board-note muted">
          「提交率模式」是手工的那几条，填的值与「未交名单」算出来的不一致。
          要么改名单，要么把模式改回自动 —— 两个数并存时，别人不知道该信哪个。
        </div>
      </div>`;
    } catch {
      return ''; // 提醒条取不到数据就不显示，不该挡住列表
    }
  },
};

export const homeworkPageDef = {
  specKey: 'homework',
  group: '教学学业',
  iconName: 'pencil',
  panel,
};

