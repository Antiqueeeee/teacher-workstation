/**
 * 学科与成绩看板：课程卡 → 课程详情（班级与名单 / 作业情况 / 学期成绩）。
 *
 * 旧应用这一块是三层嵌套页（课程 → 班级 → 学生，外加两个平行数组），
 * 全部数字在前端现算：及格线写死 60 分、分析阈值写死 80%/40 分、满分上限写死 150。
 * 这里所有**算出来的数**都来自后端（`/courses/overview`、`/courses/{id}/detail`、
 * `/courses/{id}/analysis`）—— 界面这一层只负责显示与收集输入。
 *
 * 界面上不出现任何 id：加班级填班级名、加学生填姓名、录成绩填学生姓名，
 * 名字怎么解析成 id 在后端一处（`services/course_service.py`），解析不出来会明确报错。
 */

import { api } from '../core/api.js';
import { esc } from '../core/dom.js';
import { getSpec } from '../core/store.js';
import { courseScoresPanel } from './course-scores.js';
import { openForm } from './form.js';
import { closeModal, confirmBox, openModal, toast } from './ui.js';

// 看板自己的界面状态：打开的是哪门课、在哪个页签。**只放界面状态**，
// 业务数据一律现取（见 core/store.js 的分工原则）
const state = { courseId: null, tab: 'classes' };

const TABS = [
  { key: 'classes', label: '班级与名单' },
  { key: 'homework', label: '作业情况' },
  { key: 'scores', label: '学期成绩' },
];

const rateText = (value) => (value === null || value === undefined ? '—' : `${value}%`);

function cardHtml(card) {
  const latest = card.latestExam;
  return `<div class="course-card">
    <div class="course-card-head">
      <strong>${esc(card.name)}</strong>
      ${card.teacher ? `<span class="muted">${esc(card.teacher)}</span>` : ''}
      <span class="badge">${card.classCount} 个班</span>
    </div>
    <div class="course-card-nums">
      <span>${card.studentCount} 名学生</span>
      <span>${card.hours || 0} 课时</span>
      <span>${card.homeworkCount} 次作业${
        card.homeworkRate === null ? '' : `（提交率 ${card.homeworkRate}%）`
      }</span>
      <span>${card.scoreCount} 条成绩</span>
    </div>
    <div class="muted">${
      latest
        ? `最近一场「${esc(latest.examName)}」：${latest.taken} 人次，平均得分率 ${rateText(
            latest.avgRate,
          )}，及格率 ${rateText(latest.passRate)}`
        : '还没有课程成绩'
    }</div>
    <div class="toolbar" style="margin:8px 0 0">
      <button class="btn btn-sm btn-primary" type="button" data-course-open="${card.id}">进入管理</button>
    </div>
  </div>`;
}

function blockHtml(block) {
  const roster = block.students.length
    ? `<div class="course-roster">${block.students
        .map(
          (row) => `<span class="chip">${esc(row.studentName)}${
            row.sno ? `<i class="muted"> ${esc(row.sno)}</i>` : ''
          }<button type="button" class="chip-x" title="从名单里移除"
             data-roster-del="${row.id}">×</button></span>`,
        )
        .join('')}</div>`
    : '<div class="muted">名单还是空的：点「加学生」按姓名加（可一次加一批）。</div>';

  const contact = [
    block.headTeacher
      ? `班主任 ${esc(block.headTeacher)}${block.headTeacherPhone ? `（${esc(block.headTeacherPhone)}）` : ''}`
      : '',
    block.representative
      ? `课代表 ${esc(block.representative)}${block.repPhone ? `（${esc(block.repPhone)}）` : ''}`
      : '',
  ]
    .filter(Boolean)
    .join(' · ');

  return `<div class="course-class-card">
    <div class="ccc-head">
      <strong>${esc(block.className)}</strong>
      <span class="badge">${block.studentCount} 人</span>
    </div>
    <div class="muted">${contact || '班主任与课代表还没填'}</div>
    <div class="muted">进度：${esc(block.progress || '未填写')}</div>
    <div class="muted">作业 ${block.homeworkCount} 次${
      block.homeworkRate === null ? '' : `（提交率 ${block.homeworkRate}%）`
    } · 成绩 ${block.scoreCount} 条</div>
    ${roster}
    <div class="toolbar" style="margin:8px 0 0">
      <button class="btn btn-sm" type="button" data-roster-add="${block.id}">加学生</button>
      <button class="btn btn-sm" type="button" data-class-edit="${block.id}">改班级信息</button>
    </div>
  </div>`;
}

function homeworkHtml(rows, detail) {
  if (!rows.length) {
    return '<div class="muted">这门课还没有作业。点「布置作业」记一次（提交率按未交名单自动算）。</div>';
  }
  const classNames = new Map(detail.classes.map((block) => [block.classId, block.className]));
  return `<div class="table-wrap">
    <table class="table">
      <thead><tr><th>日期</th><th>班级</th><th>作业内容</th><th>应交</th><th>未交</th><th>提交率</th><th></th></tr></thead>
      <tbody>${rows
        .map(
          (row) => `<tr>
            <td class="num">${esc(String(row.date || '').slice(0, 10))}</td>
            <td>${esc(classNames.get(row.class_id) || '')}</td>
            <td>${esc(row.content || '')}</td>
            <td class="num">${row.total || 0}</td>
            <td>${esc(row.unsubmitted_names || '无')}</td>
            <td class="num">${rateText(row.rate)}</td>
            <td class="actions">
              <button class="btn btn-sm" type="button" data-hw-edit="${row.id}">编辑</button>
              <button class="btn btn-sm btn-ghost" type="button" data-hw-del="${row.id}">删除</button>
            </td></tr>`,
        )
        .join('')}</tbody>
    </table>
  </div>`;
}

async function detailHtml(ctx) {
  const detail = await api.courseDetail(state.courseId);
  const course = detail.course;
  const totalStudents = detail.classes.reduce((sum, block) => sum + block.studentCount, 0);

  let body = '';
  if (state.tab === 'classes') {
    body = detail.classes.length
      ? `<div class="course-class-grid">${detail.classes.map(blockHtml).join('')}</div>`
      : '<div class="muted">这门课还没加班级。点「加一个班」把它教哪个班记下来 —— 名单与成绩都挂在班下面。</div>';
  } else if (state.tab === 'homework') {
    const list = await api.list('homework', {
      'filter.course_id': state.courseId,
      pageSize: 100,
      sort: 'date',
      dir: 'desc',
    });
    body = homeworkHtml(list.rows, detail);
  } else {
    body = await courseScoresPanel.html(ctx, { detail });
  }

  return `<div class="board course-board">
    <div class="board-head">
      <span class="board-title">${esc(course.name)}</span>
      <span class="muted">${detail.classes.length} 个班 · ${totalStudents} 名学生 · ${
        course.hours || 0
      } 课时${course.term ? ` · ${esc(course.term)}` : ''}</span>
      <button class="btn btn-sm" type="button" data-course-back>返回课程列表</button>
    </div>
    <div class="tabs">${TABS.map(
      (tab) =>
        `<button class="tab${state.tab === tab.key ? ' on' : ''}" type="button"
           data-course-tab="${tab.key}">${tab.label}</button>`,
    ).join('')}</div>
    <div class="tab-body">
      ${body}
      <div class="toolbar" style="margin-top:12px">
        ${
          state.tab === 'classes'
            ? '<button class="btn btn-primary" type="button" data-class-add>+ 加一个班</button>'
            : ''
        }
        ${
          state.tab === 'homework'
            ? '<button class="btn btn-primary" type="button" data-hw-add>+ 布置作业</button>'
            : ''
        }
        ${
          state.tab === 'scores'
            ? '<button class="btn btn-primary" type="button" data-score-add>+ 录一次成绩</button>'
            : ''
        }
      </div>
    </div>
  </div>`;
}

async function cardsHtml() {
  const data = await api.courseOverview();
  if (!data.courses.length) {
    return `<div class="board">
      <div class="board-head"><span class="board-title">学科与成绩</span></div>
      <div class="muted">还没有课程。任课教师先建一门课（如「数学」），再把教的班级加进来，
        名单与成绩都挂在班下面；班主任本人的常规作业不需要课程，直接记在「作业情况」里。</div>
    </div>`;
  }
  return `<div class="board">
    <div class="board-head">
      <span class="board-title">学科与成绩</span>
      <span class="muted">${data.totals.courseCount} 门课 · ${data.totals.classCount} 个班次
        · ${data.totals.homeworkCount} 次作业 · ${data.totals.scoreCount} 条成绩</span>
    </div>
    <div class="course-grid">${data.courses.map(cardHtml).join('')}</div>
  </div>`;
}

async function openRosterForm(block, ctx) {
  openModal({
    title: `加学生 · ${esc(block.className)}`,
    body: `<p class="muted">填学生姓名，多人用顿号分隔（如「张三、李四」）。
      认不出或重名的会整批不加，并在提示里说清是谁。</p>
      <textarea class="textarea" rows="4" data-names placeholder="张三、李四、王五"></textarea>`,
    footer: `<button class="btn" type="button" data-cancel>取消</button>
      <button class="btn btn-primary" type="button" data-ok>加入名单</button>`,
    onMount(root) {
      root.querySelector('[data-cancel]').addEventListener('click', closeModal);
      root.querySelector('[data-ok]').addEventListener('click', async (event) => {
        const names = root.querySelector('[data-names]').value;
        event.target.disabled = true;
        try {
          const result = await api.courseAddStudents(state.courseId, block.id, names);
          toast(
            result.added
              ? `已加入 ${result.added} 人${result.skipped ? `，${result.skipped} 人已在名单里` : ''}`
              : `${result.skipped} 人已经在名单里了`,
          );
          closeModal();
          ctx.refresh();
        } catch (error) {
          event.target.disabled = false;
          toast(error.message, 'err', 7000);
        }
      });
    },
  });
}

export const coursePanel = {
  async html(ctx) {
    try {
      return state.courseId ? await detailHtml(ctx) : await cardsHtml();
    } catch (error) {
      // 看板取不到数据不该让整页空白：把原因摆出来，列表照常可用
      return `<div class="board muted">学科与成绩没取到数据：${esc(error.message)}</div>`;
    }
  },

  bind(root, ctx) {
    root.addEventListener('click', async (event) => {
      const target = event.target;
      const open = target.closest('[data-course-open]');
      if (open) {
        state.courseId = Number(open.dataset.courseOpen);
        state.tab = 'classes';
        await ctx.refresh();
        return;
      }
      if (target.closest('[data-course-back]')) {
        state.courseId = null;
        await ctx.refresh();
        return;
      }
      const tab = target.closest('[data-course-tab]');
      if (tab) {
        state.tab = tab.dataset.courseTab;
        await ctx.refresh();
        return;
      }

      try {
        await handleAction(target, ctx);
      } catch (error) {
        toast(error.message, 'err', 7000);
      }
    });
    // 成绩页签的处理器**无条件注册**：页签是本地状态切换（refresh 只换面板内容，
    // 不会重新 bind），按当前页签决定绑不绑会让切过去之后按钮全部失灵
    courseScoresPanel.bind(root, ctx);
  },
};

const ACTIONS =
  '[data-class-add],[data-class-edit],[data-roster-add],[data-roster-del],[data-hw-add],[data-hw-edit],[data-hw-del]';

async function handleAction(target, ctx) {
  // 只有真的是本组件管的按钮才去取详情：否则每次点列表区（表头排序、翻页）都会多打一次接口
  if (!target.closest(ACTIONS)) return;
  if (!state.courseId) return;
  const detail = await api.courseDetail(state.courseId);
  const blockOf = (id) => detail.classes.find((block) => String(block.id) === String(id));

  if (target.closest('[data-class-add]')) {
    // 课程名预填：填班级名就够了（字段声明里的虚拟字段，后端按名字找班级）
    await openForm(getSpec('course_classes'), { course_name: detail.course.name });
    await ctx.refresh();
    return;
  }
  const classEdit = target.closest('[data-class-edit]');
  if (classEdit) {
    const block = blockOf(classEdit.dataset.classEdit);
    await openForm(getSpec('course_classes'), {
      id: block.id,
      course_name: detail.course.name,
      class_name: block.className,
      head_teacher: block.headTeacher,
      head_teacher_phone: block.headTeacherPhone,
      representative: block.representative,
      rep_phone: block.repPhone,
      progress: block.progress,
    });
    await ctx.refresh();
    return;
  }
  const rosterAdd = target.closest('[data-roster-add]');
  if (rosterAdd) {
    await openRosterForm(blockOf(rosterAdd.dataset.rosterAdd), ctx);
    return;
  }
  const rosterDel = target.closest('[data-roster-del]');
  if (rosterDel) {
    await api.remove('course_students', rosterDel.dataset.rosterDel);
    toast('已从名单里移除（记录仍在库里，可在「课程名单」页找回）');
    await ctx.refresh();
    return;
  }
  if (target.closest('[data-hw-add]')) {
    // 作业与「作业情况」是同一张表：这里只是把课程与科目预填好
    await openForm(getSpec('homework'), {
      course_name: detail.course.name,
      subject: detail.course.subject,
      date: new Date().toISOString().slice(0, 10),
    });
    await ctx.refresh();
    return;
  }
  const hwEdit = target.closest('[data-hw-edit]');
  if (hwEdit) {
    const row = (await api.get('homework', hwEdit.dataset.hwEdit)) || {};
    await openForm(getSpec('homework'), { ...row, course_name: detail.course.name });
    await ctx.refresh();
    return;
  }
  const hwDel = target.closest('[data-hw-del]');
  if (hwDel) {
    const yes = await confirmBox('删除这次作业？删除后仍留在库里，可在「作业情况」页勾选「显示已删除」找回。', {
      okText: '删除',
      danger: true,
    });
    if (!yes) return;
    await api.remove('homework', hwDel.dataset.hwDel);
    toast('已删除');
    await ctx.refresh();
  }
}
