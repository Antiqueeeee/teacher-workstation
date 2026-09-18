/**
 * 成绩分析。
 *
 * 页面 = 通用列表（考试管理：新增/编辑/删除考试）+ 四块这个模块特有的东西：
 * 成绩看板（选一场考试看 KPI）、名次榜、各科统计、以及三个动作
 * （成绩录入 / 科目与满分 / 清空本场成绩）。
 *
 * **所有数字都来自 `GET /exams/{id}/report`**，界面一个都不自己算：
 * 名次、及格率、得分率、单科评价、与上一场对比都在后端
 * （`services/score_stats.py`）。旧应用就是前端口径各写一遍，
 * 于是「同一场考试同一个学生在三个页面上的名次不一样」。
 *
 * 看板与三个动作共用同一个 `currentExamId`：对着 A 考试的看板点「成绩录入」，
 * 录进去的必须是 A 考试的成绩。
 */

import { openExamSubjects } from '../components/exam-subjects.js';
import { confirmClearScores, openScoreSheet } from '../components/score-sheet.js';
import { toast } from '../components/ui.js';
import { api } from '../core/api.js';
import { esc } from '../core/dom.js';
import { DASH } from '../core/format.js';
import { store } from '../core/store.js';

const EXAM_PAGE_SIZE = 100;

let currentExamId = null;

/** 分数与百分比：整数不带小数点，一位小数照实显示；空值给破折号。 */
function num(value, suffix = '') {
  if (value === null || value === undefined) return DASH;
  const text = Number.isInteger(value) ? String(value) : String(Number(value.toFixed(1)));
  return `${text}${suffix}`;
}

function delta(value, unit) {
  if (value === null || value === undefined) return DASH;
  const cls = value > 0 ? 'up' : value < 0 ? 'down' : '';
  const sign = value > 0 ? '+' : '';
  return `<span class="${cls}">${sign}${num(value)}${unit}</span>`;
}

function rankText(row) {
  if (row.rank === null || row.rank === undefined) return DASH;
  return row.tied ? `${row.rank} <span class="muted">并列</span>` : String(row.rank);
}

function cellText(row, subject) {
  if (row.absent.includes(subject)) return '<span class="score-absent">缺</span>';
  const value = row.values[subject];
  return value === undefined ? DASH : num(value);
}

/* ---------- 看板 ---------- */

function boardHead(exams, report, truncated) {
  const options = exams
    .map(
      (exam) =>
        `<option value="${exam.id}"${exam.id === report.examId ? ' selected' : ''}>${esc(
          `${exam.date.slice(0, 10)} ${exam.name}`,
        )}</option>`,
    )
    .join('');
  return `
    <div class="board-head">
      <span class="board-title">成绩看板</span>
      <select class="select" style="width:auto" data-exam-pick>${options}</select>
      <span class="muted">${esc(report.examKind)} · ${esc(report.examDate)} 满分 ${num(report.fullTotal)}</span>
      ${
        report.previous
          ? `<span class="muted">较上一场：${esc(report.previous.examName)}（${esc(report.previous.examDate)}）</span>`
          : '<span class="muted">这是本班第一场考试，没有可比的上一次</span>'
      }
    </div>
    ${truncated ? `<div class="board-note muted">考试很多，这里只列了最近的 ${EXAM_PAGE_SIZE} 场。</div>` : ''}`;
}

function kpiHtml(report) {
  return `
    <div class="kpi-row" style="margin:0">
      <div class="kpi"><div class="kpi-value">${num(report.avgTotal)}</div><div class="kpi-label">平均总分</div></div>
      <div class="kpi"><div class="kpi-value">${num(report.highestTotal)}</div><div class="kpi-label">最高</div></div>
      <div class="kpi"><div class="kpi-value">${num(report.lowestTotal)}</div><div class="kpi-label">最低</div></div>
      <div class="kpi"><div class="kpi-value">${num(report.passRate, '%')}</div><div class="kpi-label">及格率（60%）</div></div>
      <div class="kpi"><div class="kpi-value">${num(report.excellentRate, '%')}</div><div class="kpi-label">优秀率（80%）</div></div>
    </div>`;
}

function coverageHtml(report) {
  const parts = [`应考 ${report.expected}`, `实考 ${report.taken}`];
  if (report.absentStudents) parts.push(`缺考 ${report.absentStudents}`);
  if (report.unrecordedStudents) parts.push(`还没录 ${report.unrecordedStudents}`);
  const warning = report.unrecordedStudents
    ? `<span class="badge badge-beak">成绩还没录完</span> 还有 ${report.unrecordedStudents} 名学生在这一场没有任何分数，他们不计入平均分与排名。`
    : '<span class="badge badge-mint">已录齐</span>';
  return `<div class="board-note muted">${parts.join(' · ')}　${warning}</div>`;
}

/* ---------- 名次榜 ---------- */

function rankTable(report) {
  const subjects = report.subjects.map((item) => item.subject);
  const head = subjects
    .map((subject) => {
      const full = report.subjects.find((item) => item.subject === subject).fullMarks;
      return `<th class="num" title="本场满分 ${full}">${esc(subject)}</th>`;
    })
    .join('');
  const body = report.rows
    .map(
      (row) => `<tr>
        <td class="num">${rankText(row)}</td>
        <td class="score-name">${esc(row.studentName)}</td>
        <td class="num">${num(row.total)}</td>
        <td class="num">${num(row.scoreRate, '%')}</td>
        ${subjects.map((subject) => `<td class="num">${cellText(row, subject)}</td>`).join('')}
        <td class="num">${row.prevTotal === null ? DASH : num(row.total - row.prevTotal)}</td>
      </tr>`,
    )
    .join('');
  return `
    <div class="table-wrap only-wide">
      <table class="table">
        <thead><tr><th style="width:64px">名次</th><th style="min-width:96px">学生</th>
          <th class="num">总分</th><th class="num">得分率</th>${head}<th class="num">较上次</th></tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>`;
}

function rankCards(report) {
  return `
    <div class="cards only-narrow">
      ${report.rows
        .map(
          (row) => `<div class="person-card">
            <div class="card-head">
              <strong>${esc(row.studentName)}</strong>
              <span class="badge ${row.rank ? 'badge-ice' : 'badge-ink'}">${row.rank ? `第 ${row.rank} 名` : '未参加'}</span>
            </div>
            <div class="row"><span class="k">总分</span><span>${num(row.total)}${row.attemptedFull ? ` / ${row.attemptedFull}` : ''}</span></div>
            <div class="row"><span class="k">得分率</span><span>${num(row.scoreRate, '%')}</span></div>
            <div class="row"><span class="k">及格 / 优秀</span><span>${row.passed ? '及格' : '不及格'}${row.excellent ? ' · 优秀' : ''}</span></div>
            ${row.absent.length ? `<div class="row"><span class="k">缺考</span><span>${esc(row.absent.join('、'))}</span></div>` : ''}
            ${row.missing.length ? `<div class="row"><span class="k">没录</span><span>${esc(row.missing.join('、'))}</span></div>` : ''}
          </div>`,
        )
        .join('')}
    </div>`;
}

/* ---------- 各科统计 ---------- */

function subjectTable(report) {
  const rows = report.subjects
    .map((item) => {
      const diff = item.prevAvg === null || item.avg === null ? null : Number((item.avg - item.prevAvg).toFixed(1));
      return `<tr>
        <td>${esc(item.subject)}</td>
        <td class="num">${item.fullMarks}</td>
        <td class="num">${num(item.avg)}</td>
        <td class="num">${num(item.highest)}</td>
        <td class="num">${num(item.lowest)}</td>
        <td class="num">${num(item.rate, '%')}</td>
        <td class="num">${num(item.passRate, '%')}</td>
        <td>${esc(item.band)}</td>
        <td class="num">${num(item.prevAvg)}</td>
        <td class="num">${delta(diff, ' 分')}</td>
      </tr>`;
    })
    .join('');
  return `
    <table class="table">
      <thead><tr><th>科目</th><th class="num">满分</th><th class="num">平均</th><th class="num">最高</th>
        <th class="num">最低</th><th class="num">得分率</th><th class="num">及格率</th><th>评价</th>
        <th class="num">上次平均</th><th class="num">进退</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function boardHtml(exams, report, truncated) {
  return `
    <div class="board">
      ${boardHead(exams, report, truncated)}
      ${kpiHtml(report)}
      ${coverageHtml(report)}
    </div>
    <div class="board">
      <div class="board-head"><span class="board-title">名次榜</span>
        <span class="muted">同分并列（1, 2, 2, 4）；缺考与「没录」不当 0 分</span></div>
      ${rankTable(report)}
      ${rankCards(report)}
    </div>
    <div class="board">
      <div class="board-head"><span class="board-title">各科统计</span>
        <span class="muted">得分率 = 平均分 ÷ 本场该科满分；评价按得分率分档</span></div>
      <div class="table-wrap">${subjectTable(report)}</div>
    </div>`;
}

/* ---------- 页面 ---------- */

async function loadExams() {
  const list = await api.list('exams', {
    sort: 'date',
    dir: 'desc',
    pageSize: EXAM_PAGE_SIZE,
    classId: store.currentClassId,
  });
  return { exams: list.rows, truncated: (list.meta?.total || 0) > list.rows.length };
}

function currentExam() {
  return document.querySelector('[data-exam-pick]');
}

const panel = {
  async html() {
    try {
      const { exams, truncated } = await loadExams();
      if (!exams.length) {
        return `<div class="board"><div class="muted">还没有考试。先在下面「新增」一场考试，再回来录成绩。</div></div>`;
      }
      // 选中的考试被删掉时退回到最近一场，而不是让看板空着
      if (!currentExamId || !exams.some((exam) => exam.id === currentExamId)) {
        currentExamId = exams[0].id;
      }
      const report = await api.scoreReport(currentExamId);
      return boardHtml(exams, report, truncated);
    } catch (error) {
      return `<div class="board muted">成绩看板没取到数据：${esc(error.message)}</div>`;
    }
  },
  bind(root, ctx) {
    root.addEventListener('change', async (event) => {
      if (!event.target.matches('[data-exam-pick]')) return;
      currentExamId = Number(event.target.value);
      await ctx.refresh();
    });
  },
};

/** 动作作用于「看板正在看的那一场」—— 两处必须一致，否则会录错考试。 */
function pickedExam() {
  const select = currentExam();
  if (!select || !select.value) return null;
  return { id: Number(select.value), name: select.options[select.selectedIndex]?.text || '' };
}

/** 没有可选考试时告诉老师该怎么办，而不是让按钮点了没反应。 */
async function requireExam() {
  const exam = pickedExam();
  if (exam) return exam;
  const { exams } = await loadExams().catch(() => ({ exams: [] }));
  toast(
    exams.length
      ? '成绩看板还没取到数据。请刷新页面后重试。'
      : '还没有考试。请先在下面「新增」一场考试（填名称、日期、类型），再回来录成绩。',
    'err',
    8000,
  );
  return null;
}

export const scoresPageDef = {
  specKey: 'exams',
  group: '教学学业',
  iconName: 'chart',
  panel,
  actions: [
    {
      name: 'score-sheet',
      label: '成绩录入',
      iconName: 'pencil',
      primary: true,
      async run(ctx) {
        const exam = await requireExam();
        if (!exam) return;
        await openScoreSheet({ examId: exam.id, examName: exam.name, onSaved: ctx.refresh });
      },
    },
    {
      name: 'exam-subjects',
      label: '科目与满分',
      iconName: 'list',
      async run(ctx) {
        const exam = await requireExam();
        if (!exam) return;
        await openExamSubjects({ examId: exam.id, examName: exam.name, onSaved: ctx.refresh });
      },
    },
    {
      name: 'clear-scores',
      label: '清空本场成绩',
      iconName: 'trash',
      async run(ctx) {
        const exam = await requireExam();
        if (!exam) return;
        await confirmClearScores({ examId: exam.id, examName: exam.name, onDone: ctx.refresh });
      },
    },
  ],
};
