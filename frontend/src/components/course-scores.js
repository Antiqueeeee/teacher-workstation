/**
 * 学期成绩页签：各场考试的统计、分析文字、名次表、成绩生长曲线。
 *
 * 这里**一个数都不自己算**：平均分、得分率、及格率、名次、进步幅度全部来自
 * `/courses/{id}/analysis`。旧应用这些数全在前端现算，而且及格线写死 60 分
 * （150 分制科目全错）、名次按数组顺序给（同分不同名）、纵轴写死 100
 * （150 分制的点全落在框外）—— 所以这一块必须由后端给数。
 */

import { api } from '../core/api.js';
import { esc } from '../core/dom.js';
import { getSpec } from '../core/store.js';
import { lineChart } from './charts.js';
import { openForm } from './form.js';
import { confirmBox, toast } from './ui.js';

// 只看某一个班（任课教师教多个班时用）。空串 = 全部班
const state = { classId: '' };
let lastCourseId = null;

const pct = (value) => (value === null || value === undefined ? '—' : `${value}%`);
const num = (value) => (value === null || value === undefined ? '—' : String(value));

function rankBadge(item) {
  if (item.rank === null) return '<span class="muted">未排名</span>';
  if (item.rank === 1) return '<span class="badge badge-sun">第 1 名</span>';
  return `<span class="badge">第 ${item.rank} 名${item.tied ? '（并列）' : ''}</span>`;
}

function examHtml(exam) {
  const rows = exam.ranked
    .map(
      (item) => `<tr>
        <td>${esc(item.studentName)}${item.sno ? `<i class="muted"> ${esc(item.sno)}</i>` : ''}</td>
        <td>${esc(item.className)}</td>
        <td class="num">${num(item.score)}</td>
        <td class="num">${num(item.fullMarks)}</td>
        <td class="num">${pct(item.rate)}</td>
        <td>${rankBadge(item)}</td>
        <td>${item.passed ? '<span class="badge badge-mint">及格</span>' : '<span class="badge badge-rose">不及格</span>'}</td>
        <td class="actions">
          <button class="btn btn-sm" type="button" data-score-edit="${item.id}">改</button>
          <button class="btn btn-sm btn-ghost" type="button" data-score-del="${item.id}">删</button>
        </td></tr>`,
    )
    .join('');

  return `<div class="exam-block">
    <div class="exam-head">
      <strong>${esc(exam.examName)}</strong>
      <span class="muted">${esc(exam.examDate || '')}</span>
      <span class="badge">平均 ${num(exam.avg)} 分</span>
      <span class="badge badge-ice">得分率 ${pct(exam.avgRate)}</span>
      <span class="badge badge-beak">及格率 ${pct(exam.passRate)}</span>
      <span class="badge">满分 ${exam.mixedFullMarks ? '不一' : num(exam.fullMarks)}</span>
      <button class="btn btn-sm" type="button" data-score-add="${esc(exam.examName)}">补录这场</button>
    </div>
    <div class="notice ice"><div>${esc(exam.notes.join('；'))}</div></div>
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>学生</th><th>班级</th><th>分数</th><th>满分</th><th>得分率</th><th>名次</th><th>及格</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  </div>`;
}

function seriesHtml(series) {
  return `<div class="sec-title"><span class="bar"></span><h3>成绩生长曲线</h3>
      <span>每个学生各场考试的得分率走势 · 纵轴是得分率，不同满分之间才可比</span></div>
    <div class="growth-grid">${series
      .map(
        (entry) => `<div class="growth-card">
        <div class="growth-head">
          <strong>${esc(entry.studentName)}</strong>
          ${
            entry.delta === null
              ? ''
              : entry.delta > 0
                ? `<span class="badge badge-mint">↑ +${entry.delta}</span>`
                : entry.delta < 0
                  ? `<span class="badge badge-rose">↓ ${entry.delta}</span>`
                  : '<span class="badge">→ 持平</span>'
          }
          <span class="muted">最近 ${pct(entry.latest)}</span>
        </div>
        ${lineChart(
          entry.points.map((point) => ({ label: point.label, value: point.value })),
          { height: 120, suffix: '%', min: 0, max: 100 },
        )}
      </div>`,
      )
      .join('')}</div>`;
}

export const courseScoresPanel = {
  async html(ctx, { detail }) {
    const courseId = detail.course.id;
    lastCourseId = courseId;
    if (state.classId && !detail.classes.some((block) => String(block.classId) === String(state.classId))) {
      state.classId = ''; // 换了一门课（或那个班被移除了）时，别把筛选留在旧班上
    }
    let analysis;
    try {
      analysis = await api.courseAnalysis(courseId, state.classId || undefined);
    } catch (error) {
      return `<div class="muted">成绩分析没取到：${esc(error.message)}</div>`;
    }

    const filter =
      detail.classes.length > 1
        ? `<div class="toolbar" style="margin:0 0 10px">
            <select class="select" style="width:auto" data-score-class>
              <option value="">全部班级（${detail.classes.length} 个）</option>
              ${detail.classes
                .map(
                  (block) =>
                    `<option value="${block.classId}"${String(state.classId) === String(block.classId) ? ' selected' : ''}>${esc(block.className)}</option>`,
                )
                .join('')}
            </select>
            <span class="muted">切到某个班时，统计与名次只算这个班</span>
          </div>`
        : '';

    if (!analysis.exams.length) {
      return `${filter}<div class="muted">这门课还没有成绩。点「录一次成绩」按考试场次录入，
        同一场考试填同一个满分；及格与得分率按满分算，不用自己换算。</div>`;
    }

    return `${filter}
      ${analysis.exams.map(examHtml).join('')}
      ${
        analysis.series.length
          ? seriesHtml(analysis.series)
          : '<div class="muted">至少录两场考试后，这里会给出每个学生的成绩生长曲线。</div>'
      }`;
  },

  bind(root, ctx) {
    root.addEventListener('change', (event) => {
      if (!event.target.matches('[data-score-class]')) return;
      state.classId = event.target.value;
      ctx.refresh();
    });

    root.addEventListener('click', async (event) => {
      const target = event.target;
      const add = target.closest('[data-score-add]');
      const edit = target.closest('[data-score-edit]');
      const del = target.closest('[data-score-del]');
      if (!add && !edit && !del) return;

      try {
        if (add || edit) {
          const preset = {
            course_name: await courseName(),
            exam_date: new Date().toISOString().slice(0, 10),
          };
          if (add && typeof add.dataset.scoreAdd === 'string' && add.dataset.scoreAdd) {
            preset.exam_name = add.dataset.scoreAdd;
          }
          if (edit) Object.assign(preset, await scoreRow(edit.dataset.scoreEdit));
          await openForm(getSpec('course_scores'), preset);
          await ctx.refresh();
          return;
        }
        const yes = await confirmBox(
          '删掉这条成绩？删除后仍留在库里，可在「课程成绩」页勾选「显示已删除」找回。',
          { okText: '删除', danger: true },
        );
        if (!yes) return;
        await api.remove('course_scores', del.dataset.scoreDel);
        toast('已删除');
        await ctx.refresh();
      } catch (error) {
        toast(error.message, 'err', 7000);
      }
    });
  },
};

async function courseName() {
  const detail = await api.courseDetail(lastCourseId);
  return detail.course.name;
}

/** 编辑一条成绩时要把它**现有的**值填进表单（编辑表单提交的是全部字段）。 */
async function scoreRow(id) {
  const row = await api.get('course_scores', id);
  return {
    id: row.id,
    course_name: row.course_name,
    exam_name: row.exam_name,
    exam_date: row.exam_date,
    student_name: row.student_name,
    score: row.score,
    full_marks: row.full_marks,
    note: row.note,
  };
}
