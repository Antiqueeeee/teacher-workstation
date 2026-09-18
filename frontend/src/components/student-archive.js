/**
 * 学生一生一档：一个学生在这套系统里的全部痕迹，一屏看完。
 *
 * 数据来自 `GET /students/{id}/archive` —— **后端聚合**，各段的数都从所属模块的口径
 * 服务取（出勤率与出勤页同源、名次与成绩页同源、欠交次数与首页「作业待收」同源）。
 * 前端不自己算任何统计：旧应用的一生一档是前端把十几张表拉下来现算的，
 * 于是档案上的数与详情页对不上（阶段 2 的验收专门盯了这件事）。
 *
 * 特殊体质放在**最前面**：这是应急信息（发作时怎么处理、打给谁），
 * 不该等老师往下翻。
 */

import { api } from '../core/api.js';
import { esc } from '../core/dom.js';
import { errorCard } from '../core/errors.js';
import { DASH } from '../core/format.js';
import { closeModal, openModal } from './ui.js';

function dash(value) {
  return value === null || value === undefined || value === '' ? DASH : String(value);
}

function section(title, body, hint = '') {
  if (!body) return '';
  return `<div class="archive-section">
    <div class="archive-section-head"><strong>${esc(title)}</strong>
      ${hint ? `<span class="muted">${esc(hint)}</span>` : ''}</div>
    ${body}
  </div>`;
}

function listHtml(rows, render) {
  if (!rows.length) return '<div class="muted">没有记录</div>';
  return `<ul class="plain-list">${rows.map(render).join('')}</ul>`;
}

function healthHtml(health) {
  if (!health) return '';
  return `<div class="archive-alert ${health.level === '需重点关注' ? 'danger' : 'warn'}">
    <div><strong>${esc(health.type || '特殊体质')}</strong>
      <span class="badge ${health.level === '需重点关注' ? 'badge-rose' : 'badge-sun'}">${esc(health.level)}</span></div>
    ${health.detail ? `<div>情况：${esc(health.detail)}</div>` : ''}
    ${health.emergency ? `<div>发作时：${esc(health.emergency)}</div>` : ''}
    ${health.limit ? `<div>活动限制：${esc(health.limit)}</div>` : ''}
    ${health.contact ? `<div>紧急联系：${esc(health.contact)} ${esc(health.phone || '')}</div>` : ''}
  </div>`;
}

export async function openStudentArchive(student, onChanged) {
  void onChanged;
  openModal({
    title: `一生一档 · ${esc(student?.name || '')}`,
    wide: true,
    body: '<div data-archive class="muted">正在载入…</div>',
    footer: '<button class="btn" type="button" data-cancel>关闭</button>',
    onMount(root) {
      const area = root.querySelector('[data-archive]');
      root.querySelector('[data-cancel]').addEventListener('click', closeModal);

      api
        .studentArchive(student.id)
        .then((data) => {
          const extra = data.student.extra || {};
          const attendance = data.attendance;
          const typeText = Object.entries(attendance.byType)
            .map(([type, count]) => `${esc(type)} ${count}`)
            .join(' · ');

          area.innerHTML = [
            `<div class="archive-head">
              <strong>${esc(data.student.name)}</strong>
              <span class="muted">${esc(data.student.sno || '无学号')}</span>
              <span class="muted">${esc(extra.gender || '')} ${esc(extra.boarding || '')}</span>
              ${data.attachments ? `<span class="badge badge-ice">${data.attachments} 个附件</span>` : ''}
            </div>`,
            healthHtml(data.health),
            section(
              '考勤',
              `<div class="archive-stats">
                <span>出勤率 <strong>${attendance.rate === null ? DASH : `${attendance.rate}%`}</strong></span>
                <span>缺席 <strong>${attendance.absenceDays}</strong> 天</span>
                <span class="muted">（本班登记过 ${attendance.registeredDays} 天）</span>
              </div>
              ${typeText ? `<div class="muted">${typeText}</div>` : ''}
              ${listHtml(attendance.recent, (row) => `<li>${esc(row.date)} ${esc(row.type)} ${esc(row.reason || '')}${row.handled ? ` · ${esc(row.handled)}` : ''}</li>`)}`,
              '出勤率与出勤页同一算法',
            ),
            section(
              '作业',
              `<div class="archive-stats"><span>欠交 <strong>${data.homework.lateCount}</strong> 次</span></div>
               ${listHtml(data.homework.recent, (row) => `<li>${esc(row.date)} ${esc(row.subject)} ${esc(row.content)}</li>`)}`,
              '与首页「作业待收」同一张子表',
            ),
            section(
              '成绩',
              data.scores.length
                ? `<div class="table-wrap"><table class="table"><thead><tr><th>考试</th><th class="num">总分</th>
                     <th class="num">名次</th><th class="num">得分率</th><th>缺考/没录</th></tr></thead>
                   <tbody>${data.scores
                     .map(
                       (row) => `<tr><td>${esc(row.examName)}<span class="muted"> ${esc(row.examDate)}</span></td>
                         <td class="num">${dash(row.total)}</td>
                         <td class="num">${row.rank === null ? DASH : `${row.rank}/${row.studentCount}${row.tied ? ' 并列' : ''}`}</td>
                         <td class="num">${row.scoreRate === null ? DASH : `${row.scoreRate}%`}</td>
                         <td>${esc([...row.absent, ...row.missing].join('、') || '—')}</td></tr>`,
                     )
                     .join('')}</tbody></table></div>`
                : '<div class="muted">还没有成绩</div>',
              '名次由后端现算',
            ),
            section(
              '违纪',
              `<div class="archive-stats"><span>累计 <strong>${data.discipline.total}</strong> 条</span>
                 <span>未结案 <strong>${data.discipline.open}</strong></span></div>
               ${listHtml(data.discipline.recent, (row) => `<li>${esc(row.date)} ${esc(row.type)}（${esc(row.level)}·${esc(row.status)}）${esc(row.detail)}</li>`)}`,
            ),
            section(
              '沟通与谈话',
              `<div class="archive-stats">
                 <span>家长联系 <strong>${data.contacts.total}</strong>${data.contacts.followUp ? `（待跟进 ${data.contacts.followUp}）` : ''}</span>
                 <span>谈话 <strong>${data.talks.total}</strong></span>
                 <span>家访 <strong>${data.visits.total}</strong></span>
               </div>
               ${listHtml(data.contacts.recent, (row) => `<li>${esc(row.date)} ${esc(row.channel)}·${esc(row.result)} ${esc(row.content || '')}</li>`)}
               ${listHtml(data.talks.recent, (row) => `<li>${esc(row.date)} 谈话（${esc(row.type)}）${esc(row.reason || '')}</li>`)}`,
            ),
            section(
              '矛盾调解',
              `<div class="archive-stats"><span>涉及 <strong>${data.conflicts.total}</strong> 条</span></div>
               ${listHtml(data.conflicts.recent, (row) => `<li>${esc(row.date)} ${esc(row.reason)}（${esc(row.level)}·${esc(row.status)}）</li>`)}`,
            ),
            section(
              '资助',
              `<div class="archive-stats"><span>累计 <strong>${(data.grants.totalCents / 100).toFixed(2)}</strong> 元</span></div>
               ${listHtml(data.grants.recent, (row) => `<li>${esc(row.date)} ${esc(row.type)} ${esc(row.amount)} ${esc(row.status)}</li>`)}`,
            ),
          ]
            .filter(Boolean)
            .join('');
        })
        .catch((error) => {
          area.innerHTML = errorCard(error);
        });
    },
  });
}
