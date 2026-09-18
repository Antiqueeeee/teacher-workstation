/**
 * 数据看板：出勤趋势、违纪分布与 Top、沟通与大事记的月度走势。
 *
 * 三处与旧应用不同（都是它被点出来的毛病）：
 * - 出勤趋势里**未登记的日子是断开的**，不连成 100%（旧应用把没登记画成满勤）；
 * - 纵轴范围按数据自适应（旧应用写死 `min:60, max:100`）；
 * - Top 榜按 **student_id 去重**（旧应用按姓名，重名会合并成一个人）。
 */

import { barChart, hBarList, lineChart, multiLineChart } from '../components/charts.js';
import { api } from '../core/api.js';
import { esc } from '../core/dom.js';
import { errorCard } from '../core/errors.js';
import { render } from '../core/router.js';
import { store } from '../core/store.js';

const LEVEL_COLORS = { 轻微: '#f0be3c', 一般: '#ff9a3c', 严重: '#e84c4c' };
let currentDays = 14;

function panel(title, body, hint = '') {
  return `<div class="board">
    <div class="board-head"><span class="board-title">${esc(title)}</span>
      ${hint ? `<span class="muted">${esc(hint)}</span>` : ''}</div>
    ${body}
  </div>`;
}

export const dashboardPage = {
  key: 'dashboard',
  title: '数据看板',
  group: '概览',
  icon: 'chart',
  async render() {
    let data;
    try {
      data = await api.dashboard(currentDays, store.currentClassId);
    } catch (error) {
      return { html: errorCard(error) };
    }

    const registered = data.attendanceTrend.filter((day) => day.registered);
    const rates = registered.map((day) => day.rate);
    const latest = registered[registered.length - 1];
    const average = rates.length ? Math.round(rates.reduce((sum, value) => sum + value, 0) / rates.length) : null;

    const trendPoints = data.attendanceTrend.map((day) => ({
      label: day.date.slice(5),
      value: day.registered ? day.rate : null, // 未登记 → 断开
    }));
    const levels = Object.entries(data.discipline.byLevel).map(([label, value]) => ({
      label,
      value,
      color: LEVEL_COLORS[label] || '#93a9b5',
    }));
    const types = Object.entries(data.discipline.byType)
      .map(([label, value]) => ({ label, value }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 6);

    const html = `
      <div class="board">
        <div class="board-head"><span class="board-title">近 ${data.days} 天</span>
          ${[7, 14, 30]
            .map(
              (days) =>
                `<button class="btn btn-sm${days === currentDays ? ' btn-primary' : ''}" type="button"
                   data-days="${days}">${days} 天</button>`,
            )
            .join('')}
          <span class="muted">未登记的日子在折线里是断开的（不是满勤）</span></div>
        <div class="kpi-row" style="margin:0">
          <div class="kpi"><div class="kpi-value">${average === null ? '—' : `${average}%`}</div>
            <div class="kpi-label">平均出勤率（已登记的 ${registered.length} 天）</div></div>
          <div class="kpi"><div class="kpi-value">${latest ? latest.rate : '—'}${latest ? '%' : ''}</div>
            <div class="kpi-label">最近一次登记${latest ? `（${esc(latest.date)}）` : ''}</div></div>
          <div class="kpi"><div class="kpi-value">${data.discipline.total}</div><div class="kpi-label">违纪记录</div></div>
          <div class="kpi"><div class="kpi-value">${data.discipline.open}</div><div class="kpi-label">未结案</div></div>
        </div>
        ${lineChart(trendPoints, { suffix: '%', min: 0, max: 100 })}
      </div>

      ${panel('违纪情况', `
        <div class="chart-row">
          <div><div class="muted">按程度</div>${barChart(levels, { height: 130 })}</div>
          <div><div class="muted">按类型（前 6）</div>${
            types.length ? hBarList(types, { suffix: ' 次' }) : '<div class="muted">没有数据</div>'
          }</div>
        </div>`)}

      ${panel('缺勤 Top 5', data.absentTop.length
        ? hBarList(
            data.absentTop.map((row) => ({ label: row.studentName, value: row.count })),
            { suffix: ' 天' },
          )
        : '<div class="muted">近 ${data.days} 天没有缺勤记录</div>',
        '按人算（重名不会合并）')}

      ${panel('违纪 Top 5', data.discipline.top.length
        ? hBarList(
            data.discipline.top.map((row) => ({ label: row.studentName, value: row.count })),
            { suffix: ' 次' },
          )
        : '<div class="muted">没有违纪记录</div>')}

      ${panel('近几个月：联系 / 谈话 / 大事记', multiLineChart(
        [
          { label: '家长联系', values: data.monthly.contacts },
          { label: '谈话', values: data.monthly.talks },
          { label: '大事记', values: data.monthly.events },
        ],
        data.months.map((month) => month.slice(2)),
      ))}`;

    return {
      html,
      bind(root) {
        root.addEventListener('click', async (event) => {
          const button = event.target.closest('[data-days]');
          if (!button) return;
          currentDays = Number(button.dataset.days);
          await render();
        });
      },
    };
  },
};
