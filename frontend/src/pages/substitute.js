/**
 * 代课 / 交接简报：某一天的班级情况，给临时来代的老师看，**可以打印**。
 *
 * 顺序是刻意的：**特殊体质放最前面** —— 那是安全信息（发作怎么处理、打给谁），
 * 代课老师第一时间要知道；然后是今天谁没来、有事找谁（班委）、值班安排、要留意的几个学生、
 * 班规、座位图。
 *
 * 数据全部来自 `GET /analytics/substitute` —— 后端汇总，用的还是各模块自己的口径
 * （考勤来自出勤口径、座位来自座位表）。旧应用的简报也是只读页，但它把课表、缺席、
 * 体质、纪律、班规、座位图各算了一遍，口径与详情页对不上。
 */

import { api } from '../core/api.js';
import { esc } from '../core/dom.js';
import { errorCard } from '../core/errors.js';
import { todayISO } from '../core/format.js';
import { render } from '../core/router.js';
import { store } from '../core/store.js';

let currentDay = todayISO();

function block(title, body, hint = '') {
  if (!body) return '';
  return `<div class="brief-block">
    <div class="brief-block-head"><strong>${esc(title)}</strong>
      ${hint ? `<span class="muted">${esc(hint)}</span>` : ''}</div>
    ${body}
  </div>`;
}

function attendanceHtml(data) {
  if (!data.registered) {
    return '<div class="brief-alert warn">这一天还没登记考勤 —— 缺席名单可能不准，请以实际为准。</div>';
  }
  const names = data.absentStudents.length ? data.absentStudents.join('、') : '无';
  return `<div class="brief-stats">
      <span>应到 <strong>${data.expected}</strong></span>
      <span>缺席 <strong>${data.absent}</strong></span>
      <span>迟到 <strong>${data.late}</strong></span>
      <span>早退 <strong>${data.early}</strong></span>
    </div>
    <div>缺席名单：${esc(names)}</div>`;
}

function healthHtml(rows) {
  if (!rows.length) return '';
  return rows
    .map(
      (row) => `<div class="brief-alert danger">
        <strong>${esc(row.studentName)}</strong> · ${esc(row.type || '')}
        ${row.detail ? `<div>情况：${esc(row.detail)}</div>` : ''}
        ${row.emergency ? `<div><strong>发作时：${esc(row.emergency)}</strong></div>` : ''}
        ${row.limit ? `<div>活动限制：${esc(row.limit)}</div>` : ''}
        ${row.contact ? `<div>联系：${esc(row.contact)} ${esc(row.phone || '')}</div>` : ''}
      </div>`,
    )
    .join('');
}

function seatsHtml(seats) {
  if (!seats.rows) return '';
  const head = `<tr><th></th>${Array.from({ length: seats.cols }, (_, index) => `<th>${index + 1} 列</th>`).join('')}</tr>`;
  const rows = seats.grid
    .map(
      (line, index) =>
        `<tr><th>${index + 1} 排</th>${line
          .map((cell) => `<td>${esc(cell.studentName || '')}</td>`)
          .join('')}</tr>`,
    )
    .join('');
  return `<div class="seat-grid-wrap"><div class="seat-podium">讲　台</div>
    <table class="seat-grid brief-seats"><thead>${head}</thead><tbody>${rows}</tbody></table></div>`;
}

export const substitutePage = {
  key: 'substitute',
  title: '代课简报',
  group: '概览',
  icon: 'print',
  async render() {
    let data;
    try {
      data = await api.substituteBrief(currentDay, store.currentClassId);
    } catch (error) {
      return { html: errorCard(error) };
    }

    const html = `
      <div class="board">
        <div class="board-head no-print">
          <span class="board-title">代课 / 交接简报</span>
          <input class="input" type="date" style="width:auto" data-day value="${esc(currentDay)}">
          <button class="btn btn-sm" type="button" data-today>今天</button>
          <button class="btn btn-sm btn-primary" type="button" data-print>打印</button>
        </div>
        <div class="brief-head">
          <strong>${esc(data.date)}　${esc(data.weekday)}</strong>
          ${data.missingSections.length ? `<span class="muted no-print">暂缺：${esc(data.missingSections.join('、'))}</span>` : ''}
        </div>

        ${block(
          '今天的课表',
          data.todaySlots && data.todaySlots.length
            ? `<ul class="plain-list">${data.todaySlots
                .map(
                  (slot) =>
                    `<li>${esc(slot.period)}：${esc(slot.subject || '（没填科目）')}
                      ${slot.teacher ? `· ${esc(slot.teacher)}` : ''}${slot.room ? ` · ${esc(slot.room)}` : ''}</li>`,
                )
                .join('')}</ul>`
            : '<div class="muted">课表里还没排今天（或者今天本来就没课）</div>',
        )}
        ${block('一定要先看的（特殊体质）', healthHtml(data.health))}
        ${block('今天的考勤', attendanceHtml(data.attendance))}
        ${block(
          '有事找他们（班委）',
          data.cadres.length
            ? `<div class="brief-stats">${data.cadres
                .map((row) => `<span>${esc(row.post)}：${esc(row.studentName)} ${esc(row.phone || '')}</span>`)
                .join('')}</div>`
            : '',
        )}
        ${block(
          '今天值日',
          data.duty.length
            ? `<ul class="plain-list">${data.duty
                .map((row) => `<li>${esc(row.area)}：${esc(row.members)}${row.leader ? `（组长 ${esc(row.leader)}）` : ''}</li>`)
                .join('')}</ul>`
            : '',
        )}
        ${block(
          '要多留意的学生（未结案）',
          data.discipline.length
            ? `<ul class="plain-list">${data.discipline
                .map(
                  (row) =>
                    `<li>${esc(row.studentName)} —— ${esc(row.date)} ${esc(row.type)}（${esc(row.level)}·${esc(row.status)}）</li>`,
                )
                .join('')}</ul>`
            : '',
        )}
        ${block(
          '班规（节选）',
          data.rules.length
            ? `<ul class="plain-list">${data.rules
                .map((row) => `<li><strong>${esc(row.title)}</strong>${row.category ? `（${esc(row.category)}）` : ''}${row.content ? `：${esc(row.content)}` : ''}</li>`)
                .join('')}</ul>`
            : '',
        )}
        ${block('座位表', seatsHtml(data.seats))}
      </div>`;

    return {
      html,
      bind(root) {
        root.addEventListener('click', async (event) => {
          if (event.target.closest('[data-print]')) {
            window.print();
            return;
          }
          if (event.target.closest('[data-today]')) {
            currentDay = todayISO();
            await render(); // 换日期就重绘这一页（router 的 render 会用当前 hash）
          }
        });
        root.addEventListener('change', async (event) => {
          if (!event.target.matches('[data-day]')) return;
          currentDay = event.target.value || todayISO();
          await render();
        });
      },
    };
  },
};
