/**
 * 成绩录入表：学生 × 科目 的网格，按**格**提交。
 *
 * 三态在界面上要能一眼区分，所以一格里只填一种东西：
 * - **数字**（可带一位小数）= 分数；
 * - **「缺」**（也认 缺考/x/-）= 缺考；
 * - **留空** = 还没录。
 *
 * 为什么不给每格配一个「缺考」勾选框：45 人 × 9 科是 405 个格子，
 * 每格两个控件会让这张表没法用。打字比勾选快，这也和老师手里的成绩表长得一样。
 *
 * 只提交**改动过的格子**：成绩表很长，全量提交会因为界面没滚动到而把别处抹掉
 * （后端也是按格更新，两边一致）。清空一格就是把它删回「留空」。
 */

import { api } from '../core/api.js';
import { esc } from '../core/dom.js';
import { errorCard } from '../core/errors.js';
import { closeModal, confirmBox, openModal, toast } from './ui.js';

const ABSENT_WORDS = new Set(['缺', '缺考', '未考', 'x', 'X', '×', '-', '—', '/']);

function cellText(value, absent) {
  if (absent) return '缺';
  if (value === null || value === undefined) return '';
  return String(value);
}

/** 一格的输入值 → 提交形状；不合法时返回一条给老师看的话。 */
function readCell(raw, fullMarks) {
  const text = String(raw ?? '').trim();
  if (text === '') return { value: null, absent: false };
  if (ABSENT_WORDS.has(text)) return { value: null, absent: true };
  const number = Number(text);
  if (Number.isNaN(number)) return { error: `「${text}」既不是分数也不是「缺」` };
  if (number < 0 || number > fullMarks) return { error: `分数要在 0–${fullMarks} 之间` };
  return { value: Math.round(number * 10) / 10, absent: false };
}

function sameCell(a, b) {
  return (a.value ?? null) === (b.value ?? null) && Boolean(a.absent) === Boolean(b.absent);
}

function rowStatus(cells) {
  const absent = cells.filter((cell) => cell.absent).length;
  const missing = cells.filter((cell) => !cell.absent && cell.value === null).length;
  const parts = [];
  if (absent) parts.push(`缺考 ${absent}`);
  if (missing) parts.push(`未录 ${missing}`);
  return parts.length ? parts.join(' · ') : '已录齐';
}

/* ---------- 宽屏：一张表 ---------- */

function tableHtml(subjects, students) {
  const head = subjects
    .map(
      (item) =>
        `<th class="num" title="满分 ${item.fullMarks}">${esc(item.subject)}<span class="muted">/${item.fullMarks}</span></th>`,
    )
    .join('');
  const body = students
    .map(
      (student) => `<tr data-student-row="${student.studentId}">
        <td class="score-name">${esc(student.studentName)}<span class="muted">${esc(student.sno || '')}</span></td>
        ${subjects
          .map((item) => {
            const cell = student.cells[item.subject] || { value: null, absent: false };
            return `<td><input class="input score-cell" data-student="${student.studentId}"
              data-subject="${esc(item.subject)}" data-full="${item.fullMarks}"
              inputmode="decimal" value="${esc(cellText(cell.value, cell.absent))}"></td>`;
          })
          .join('')}
        <td class="score-status muted" data-status></td>
      </tr>`,
    )
    .join('');

  return `
    <div class="table-wrap only-wide">
      <table class="table score-table">
        <thead><tr><th style="min-width:110px">学生</th>${head}<th>状态</th></tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>`;
}

/* ---------- 窄屏：一人一张卡（竖着填，不用左右拖） ---------- */

function cardsHtml(subjects, students) {
  return `
    <div class="cards only-narrow">
      ${students
        .map(
          (student) => `<div class="person-card" data-student-card="${student.studentId}">
            <div class="card-head">
              <strong>${esc(student.studentName)}</strong>
              <span class="muted">${esc(student.sno || '')}</span>
            </div>
            ${subjects
              .map((item) => {
                const cell = student.cells[item.subject] || { value: null, absent: false };
                return `<div class="score-field">
                  <span class="k">${esc(item.subject)}<span class="muted">/${item.fullMarks}</span></span>
                  <input class="input score-cell" data-student="${student.studentId}"
                    data-subject="${esc(item.subject)}" data-full="${item.fullMarks}"
                    inputmode="decimal" value="${esc(cellText(cell.value, cell.absent))}">
                </div>`;
              })
              .join('')}
            <div class="muted" data-status></div>
          </div>`,
        )
        .join('')}
    </div>`;
}

export async function openScoreSheet({ examId, examName, onSaved } = {}) {
  let sheet = null;
  let original = new Map(); // "studentId|subject" → {value, absent}

  openModal({
    title: `成绩录入 · ${esc(examName || '')}`,
    wide: true,
    body: `
      <div class="score-hint muted">
        分数填数字（可带一位小数），<strong>缺考填「缺」</strong>，留空表示还没录。
        只提交你改动的格子。
      </div>
      <div data-sheet><div class="muted">正在载入…</div></div>`,
    footer: `
      <span class="muted" style="margin-right:auto" data-sheet-hint></span>
      <button class="btn" type="button" data-cancel>取消</button>
      <button class="btn btn-primary" type="button" data-save>保存成绩</button>`,
    onMount(root) {
      const sheetArea = root.querySelector('[data-sheet]');
      const hint = root.querySelector('[data-sheet-hint]');
      const saveButton = root.querySelector('[data-save]');
      root.querySelector('[data-cancel]').addEventListener('click', closeModal);

      const key = (studentId, subject) => `${studentId}|${subject}`;

      /** 界面上每格的当前值（读 DOM，不另存一份状态，免得两处漂） */
      function currentCells() {
        const cells = [];
        root.querySelectorAll('.score-cell').forEach((input) => {
          const parsed = readCell(input.value, Number(input.dataset.full));
          cells.push({
            studentId: Number(input.dataset.student),
            subject: input.dataset.subject,
            ...parsed,
          });
        });
        return cells;
      }

      function renderStatus() {
        if (!sheet) return;
        // 状态写在每行/每张卡上，宽屏与窄屏各一份 DOM，逐个更新
        root.querySelectorAll('[data-student-row]').forEach((row) => {
          updateStatus(row.querySelector('[data-status]'), Number(row.dataset.studentRow));
        });
        root.querySelectorAll('[data-student-card]').forEach((card) => {
          updateStatus(card.querySelector('[data-status]'), Number(card.dataset.studentCard));
        });
        const changed = dirtyCells().length;
        hint.textContent = changed ? `有 ${changed} 处改动还没保存` : '还没有改动';
      }

      function updateStatus(node, studentId) {
        if (!node || !sheet) return;
        const cells = [];
        root.querySelectorAll(`.score-cell[data-student="${studentId}"]`).forEach((input) => {
          cells.push(readCell(input.value, Number(input.dataset.full)));
        });
        // 宽屏与窄屏两份 DOM 只有一份可见，但状态文案两边都写，切换窗口宽度时也是对的
        const status = rowStatus(cells.map((cell) => ({ value: cell.value, absent: cell.absent })));
        node.textContent = status;
        node.classList.toggle('ok', status === '已录齐');
      }

      function dirtyCells() {
        if (!sheet) return [];
        const result = [];
        for (const cell of currentCells()) {
          const before = original.get(key(cell.studentId, cell.subject)) || { value: null, absent: false };
          if (cell.error) continue;
          if (!sameCell(before, cell)) result.push(cell);
        }
        return result;
      }

      async function load() {
        sheetArea.innerHTML = '<div class="muted">正在载入…</div>';
        try {
          sheet = await api.scoreSheet(examId);
        } catch (error) {
          sheetArea.innerHTML = errorCard(error);
          return;
        }
        original = new Map();
        for (const student of sheet.students) {
          for (const subject of Object.keys(student.cells)) {
            original.set(key(student.studentId, subject), student.cells[subject]);
          }
        }
        sheetArea.innerHTML = tableHtml(sheet.subjects, sheet.students) + cardsHtml(sheet.subjects, sheet.students);
        renderStatus();
        // 自动聚焦第一个格子：老师打开就想开始填，不该再点一次
        const first = sheetArea.querySelector('.score-cell');
        if (first) first.focus();
      }

      sheetArea.addEventListener('input', renderStatus);

      saveButton.addEventListener('click', async () => {
        if (!sheet) return;
        const invalid = currentCells().find((cell) => cell.error);
        if (invalid) {
          toast(`${invalid.subject}：${invalid.error}`, 'err', 6000);
          return;
        }
        const cells = dirtyCells();
        if (!cells.length) {
          toast('没有改动');
          return;
        }
        saveButton.disabled = true;
        try {
          const data = await api.saveScoreSheet(
            examId,
            cells.map(({ studentId, subject, value, absent }) => ({ studentId, subject, value, absent })),
          );
          const parts = [];
          if (data.changes.created) parts.push(`新增 ${data.changes.created}`);
          if (data.changes.updated) parts.push(`修改 ${data.changes.updated}`);
          if (data.changes.removed) parts.push(`清空 ${data.changes.removed}`);
          toast(parts.length ? `已保存：${parts.join('、')}` : '已保存');
          closeModal();
          if (onSaved) onSaved();
        } catch (error) {
          toast(error.message, 'err', 7000);
        } finally {
          saveButton.disabled = false;
        }
      });

      load();
    },
  });
}

/** 「清空本场成绩」—— 破坏性操作，问清楚再动手，并说明影响多少条。 */
export async function confirmClearScores({ examId, examName, onDone } = {}) {
  const yes = await confirmBox(
    `清空「${esc(examName || '')}」的全部成绩？考试本身会留着，但这个班这场的成绩会全部删掉，不能恢复。`,
    { okText: '清空成绩', danger: true },
  );
  if (!yes) return;
  try {
    const data = await api.clearExamScores(examId);
    toast(data.removed ? `已清空 ${data.removed} 条成绩` : '这场本来就没有成绩');
    if (onDone) onDone();
  } catch (error) {
    toast(error.message, 'err', 6000);
  }
}
