/**
 * 一周课表网格：行是节次、列是星期，一格一门课。
 *
 * 排格子在后端做（`services/schedule_service.week_view`）—— 界面不必知道
 * 节次的先后与星期的顺序，也不必自己判断「这一格有没有课」。
 * 点格子不做编辑（这里是**看**的视角）；增删改在下面的列表里做，
 * 那样导入导出、软删除找回这些能力都还在。
 */

import { api } from '../core/api.js';
import { esc } from '../core/dom.js';
import { store } from '../core/store.js';

export const weekGridPanel = {
  async html() {
    let data;
    try {
      data = await api.scheduleWeek(store.currentClassId);
    } catch (error) {
      return `<div class="board muted">课表没取到数据：${esc(error.message)}</div>`;
    }
    const head = data.weekdays.map((day) => `<th>${esc(day)}</th>`).join('');
    const body = data.periods
      .map(
        (period, index) => `<tr>
          <th class="week-row-head">${esc(period)}</th>
          ${data.grid
            .map((column) => {
              const cell = column[index];
              if (!cell || !cell.slotId) return '<td class="week-cell empty"></td>';
              const extra = [cell.teacher, cell.room].filter(Boolean).join(' · ');
              return `<td class="week-cell"><strong>${esc(cell.subject || '（未填科目）')}</strong>${
                extra ? `<span class="muted">${esc(extra)}</span>` : ''
              }</td>`;
            })
            .join('')}
        </tr>`,
      )
      .join('');

    return `<div class="board">
      <div class="board-head"><span class="board-title">这一周的课表</span>
        <span class="muted">一格一门课；要改就在下面的列表里改</span></div>
      <div class="table-wrap">
        <table class="table week-grid">
          <thead><tr><th></th>${head}</tr></thead>
          <tbody>${body}</tbody>
        </table>
      </div>
    </div>`;
  },
};
