/**
 * 工作台首页：一屏看完今天该干什么。
 *
 * **只读聚合页**，不上通用列表那套 —— 它显示的数全部来自后端
 * `GET /analytics/overview` 与 `/analytics/followups`，而那两个接口又从各模块自己的
 * 口径服务里取数。旧应用首页的问题就是「同一件事在首页和详情页各算一遍」：
 * 「作业待收」读两个不存在的字段（恒为 0），而列表页另有一个算法。
 *
 * 跟进清单的每一条都能**直接落到那条记录**（带着搜索词跳到该模块的列表页），
 * 而不是像旧应用那样只跳到模块首页、让老师自己找。
 */

import { api } from '../core/api.js';
import { esc } from '../core/dom.js';
import { errorCard } from '../core/errors.js';
import { DASH } from '../core/format.js';
import { getSpec, getListState, store } from '../core/store.js';

const PAGE_LABELS = {
  attendance: '出勤记录',
  contacts: '家长联系日志',
  homework: '作业情况',
  todos: '待办任务',
};

function kpi(label, value, hint = '') {
  return `<div class="kpi">
    <div class="kpi-value">${value === null || value === undefined ? DASH : esc(String(value))}</div>
    <div class="kpi-label">${esc(label)}</div>
    ${hint ? `<div class="muted">${esc(hint)}</div>` : ''}
  </div>`;
}

function todoCards(data) {
  const attendance = data.attendance.registered
    ? { n: 0, title: '考勤', sub: '今天已登记', tone: 'ok' }
    : { n: 1, title: '考勤', sub: '今天还没登记考勤', tone: 'warn' };
  const homework = {
    n: data.homework.pending,
    title: '作业',
    sub: data.homework.pending ? `${data.homework.pending} 次还没交齐` : '都交齐了',
    tone: data.homework.pending ? 'warn' : 'ok',
  };
  const contacts = {
    n: data.contacts.followUp,
    title: '家长',
    sub: data.contacts.followUp ? `${data.contacts.followUp} 条要再联系` : '没有待跟进的',
    tone: data.contacts.followUp ? 'warn' : 'ok',
  };
  const todos = {
    n: data.todos.open,
    title: '待办',
    sub: data.todos.open ? `${data.todos.open} 项没做` : '都清完了',
    tone: data.todos.open ? 'warn' : 'ok',
  };
  return [attendance, homework, contacts, todos]
    .map(
      (card) => `<div class="todo-card ${card.tone}">
        <div class="todo-card-head"><span>${esc(card.title)}</span>
          <span class="todo-count">${card.n}</span></div>
        <div class="muted">${esc(card.sub)}</div>
      </div>`,
    )
    .join('');
}

function followupHtml(items) {
  if (!items.length) {
    return '<div class="muted">暂时没有需要跟进的事。</div>';
  }
  return `<ul class="followup-list">${items
    .map(
      (item) => `<li>
        <button class="followup-item" type="button"
          data-table="${esc(item.table)}" data-name="${esc(item.studentName || '')}">
          <span class="followup-text">${esc(item.text)}</span>
          <span class="muted">${esc(PAGE_LABELS[item.table] || item.table)}</span>
        </button>
      </li>`,
    )
    .join('')}</ul>`;
}

/** 跳到某个模块的列表，并把搜索框预填成这个人 —— 老师落地就是筛好的那一条。 */
function openRecord(table, name) {
  const spec = getSpec(table);
  if (spec) {
    const state = getListState(spec);
    state.q = name || '';
    state.page = 1;
  }
  window.location.hash = table;
}

export const homePage = {
  key: 'home',
  title: '工作台首页',
  group: '概览',
  icon: 'home',
  async render() {
    let data;
    let items;
    let feed;
    try {
      [data, items, feed] = await Promise.all([
        api.overview(store.currentClassId),
        api.followups(store.currentClassId, 14),
        api.timeline(store.currentClassId, 8),
      ]);
    } catch (error) {
      return { html: errorCard(error) };
    }

    const attendanceLine = data.attendance.registered
      ? `今天出勤率 ${data.attendance.rate === null ? DASH : `${data.attendance.rate}%`}` +
        (data.attendance.absent ? ` · 缺席 ${data.attendance.absent}` : '') +
        (data.attendance.late ? ` · 迟到 ${data.attendance.late}` : '') +
        (data.attendance.early ? ` · 早退 ${data.attendance.early}` : '')
      : '今天还没登记考勤';

    const html = `
      <div class="board">
        <div class="board-head"><span class="board-title">${esc(data.date)} 概况</span>
          <span class="muted">${esc(attendanceLine)}</span></div>
        <div class="kpi-row" style="margin:0">
          ${kpi('学生', data.students.total)}
          ${kpi('住宿生', data.students.boarding)}
          ${kpi('平均提交率', data.homework.averageRate === null ? DASH : `${data.homework.averageRate}%`)}
          ${kpi('附件', data.attachments)}
          ${
            data.students.duplicateNames
              ? kpi('同名', data.students.duplicateNames, '到学生档案处理')
              : ''
          }
        </div>
      </div>

      <div class="board">
        <div class="board-head"><span class="board-title">今日待办</span></div>
        <div class="todo-cards">${todoCards(data)}</div>
      </div>

      <div class="board">
        <div class="board-head"><span class="board-title">需要我跟进</span>
          <span class="muted">点一条跳到那条记录</span></div>
        ${followupHtml(items)}
      </div>

      <div class="board">
        <div class="board-head"><span class="board-title">最近动态</span>
          <span class="muted">沟通留档与班级事务按日期合并</span></div>
        ${
          feed.length
            ? `<ul class="plain-list">${feed
                .map(
                  (item) =>
                    `<li>${esc(item.date)} <span class="badge badge-ice">${esc(item.label)}</span>
                      ${esc(item.studentName ? `${item.studentName} ` : '')}${esc(item.text)}</li>`,
                )
                .join('')}</ul>`
            : '<div class="muted">还没有记录</div>'
        }
      </div>

      <div class="board">
        <div class="board-head"><span class="board-title">常用入口</span></div>
        <div class="quick-links">
          ${[
            ['students', '学生档案'],
            ['attendance', '出勤记录'],
            ['homework', '作业情况'],
            ['scores', '成绩分析'],
            ['contacts', '家长联系日志'],
            ['dorms', '宿舍分布'],
            ['seats', '座位安排'],
            ['dorm_duties', '宿舍值日'],
          ]
            .map(
              ([key, label]) =>
                `<button class="btn btn-sm" type="button" data-go="${key}">${esc(label)}</button>`,
            )
            .join('')}
        </div>
      </div>`;

    return {
      html,
      bind(root) {
        root.addEventListener('click', (event) => {
          const item = event.target.closest('[data-table]');
          if (item) {
            openRecord(item.dataset.table, item.dataset.name);
            return;
          }
          const go = event.target.closest('[data-go]');
          if (go) window.location.hash = go.dataset.go;
        });
      },
    };
  },
};
