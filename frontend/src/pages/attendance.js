/**
 * 出勤记录。
 *
 * 页面 = 通用列表（照旧，用来查/改/导入导出明细）+ 两块这个模块特有的东西：
 *
 * 1. **出勤看板**：某天的出勤率、应到、缺席、迟到/早退。数字全部由后端
 *    `services/attendance_rate.py` 算出 —— 界面这层只负责显示，不自己数记录条数。
 *    旧应用的三处出勤率就是各自数出来的，最后谁跟谁都不一样。
 * 2. **点名**：一天一次、整批提交（见 components/roll-call.js）。
 *
 * 看板与点名共用同一个 `currentDay`：点「点名」时打开的必须是看板正在看的这一天，
 * 否则老师会对着 9 月 18 日的看板改 9 月 19 日的考勤，而且看不出来。
 */

import { openRollCall } from '../components/roll-call.js';
import { api } from '../core/api.js';
import { esc } from '../core/dom.js';
import { DASH, shiftDay, todayISO } from '../core/format.js';
import { store } from '../core/store.js';

let currentDay = todayISO();

function rateText(rate) {
  // 未登记、应到 0 人时后端给 null —— 显示「—」，而不是看起来像满勤的 100%
  return rate === null || rate === undefined ? DASH : `${rate}%`;
}

function noteText(day) {
  if (!day.registered) return '这天还没登记考勤。点「点名」开始登记。';
  if (day.absent === 0) return `全天出勤，没有缺席。${day.late || day.early ? '迟到早退见右侧指标。' : ''}`;
  return `缺席：${day.absentStudents.join('、')}`;
}

function boardHtml(summary) {
  const day = summary.days[0];
  return `
    <div class="board">
      <div class="board-head">
        <span class="board-title">出勤看板</span>
        <button class="btn btn-sm" type="button" data-day-nav="-1" title="前一天">‹</button>
        <input class="input" type="date" data-board-day value="${esc(currentDay)}">
        <button class="btn btn-sm" type="button" data-day-nav="1" title="后一天">›</button>
        <button class="btn btn-sm" type="button" data-day-nav="today">今天</button>
      </div>
      <div class="kpi-row" style="margin:0">
        <div class="kpi"><div class="kpi-value">${rateText(day.rate)}</div><div class="kpi-label">出勤率</div></div>
        <div class="kpi"><div class="kpi-value">${day.expected}</div><div class="kpi-label">应到</div></div>
        <div class="kpi"><div class="kpi-value">${day.absent}</div><div class="kpi-label">缺席</div></div>
        <div class="kpi"><div class="kpi-value">${day.late} / ${day.early}</div><div class="kpi-label">迟到 / 早退</div></div>
      </div>
      <div class="board-note muted">${esc(noteText(day))}</div>
      <div class="board-note muted">
        出勤率 = (应到 − 缺席) / 应到；缺席按<strong>人数</strong>算（同一人多条只算一次），
        迟到、早退单列，不计入缺席。没登记的日子不按满勤算。
      </div>
    </div>`;
}

const panel = {
  async html() {
    try {
      const summary = await api.attendanceSummary(currentDay, currentDay, store.currentClassId);
      return boardHtml(summary);
    } catch (error) {
      // 看板失败不该把整个列表页拖down —— 列表自己会再报一次
      return `<div class="card muted">出勤看板没取到数据：${esc(error.message)}</div>`;
    }
  },
  bind(root, ctx) {
    root.addEventListener('click', async (event) => {
      const nav = event.target.closest('[data-day-nav]');
      if (!nav) return;
      const step = nav.dataset.dayNav;
      currentDay = step === 'today' ? todayISO() : shiftDay(currentDay, Number(step));
      await ctx.refresh();
    });
    root.addEventListener('change', async (event) => {
      if (!event.target.matches('[data-board-day]')) return;
      currentDay = event.target.value || todayISO();
      await ctx.refresh();
    });
  },
};

export const attendancePageDef = {
  specKey: 'attendance',
  group: '教学学业',
  iconName: 'calendar',
  panel,
  actions: [
    {
      name: 'roll-call',
      label: '点名',
      iconName: 'check',
      primary: true,
      async run(ctx) {
        await openRollCall({
          classId: store.currentClassId,
          day: currentDay,
          onSaved: ctx.refresh,
        });
      },
    },
  ],
};

// 缺席类型的判定在后端（services/attendance_rate.py 的 ABSENCE_TYPES）；
// 界面不去猜哪些算缺席，只显示后端算好的数字
