/**
 * 学生档案。
 *
 * 与别的页面**没有任何区别** —— 因为学生档案的表声明也会出现在 `/meta/registry` 里
 * （后端把它当「动态表」注册，声明按库里的字段定义现算）。
 * 所以字段管理里加一个字段，刷新页面这个列表和表单就多一列。
 *
 * 独有的一块是顶部的**同名/同学号提醒**：姓名是老师习惯的输入，但姓名不是唯一标识。
 * 写入口（监护人、出勤）撞到重名时会报错让人确认，可那是**一条一条**发现的 ——
 * 老师得先撞上一次才知道班上有重名。这里一次列全，让老师能主动去改。
 */

import { openStudentArchive } from '../components/student-archive.js';
import { openCommentDraft } from '../components/comment-draft.js';
import { api } from '../core/api.js';
import { esc } from '../core/dom.js';
import { store } from '../core/store.js';

function groupText(items, label, key) {
  return items
    .map(
      (group) =>
        `<li>${esc(label)}「${esc(group[key])}」：${group.students
          .map((item) => `${esc(item.name)}（${esc(item.sno || '无学号')}）`)
          .join('、')}</li>`,
    )
    .join('');
}

const panel = {
  async html() {
    let data;
    try {
      data = await api.studentConflicts(store.currentClassId);
    } catch {
      return ''; // 提醒取不到就算了，不该挡住档案本身
    }
    const names = data?.names || [];
    if (!names.length) return '';

    return `<div class="board">
      <div class="board-head"><span class="board-title">有同名同学，先处理一下</span>
        <span class="muted">同名 ${names.length} 组</span></div>
      <ul class="plain-list">
        ${groupText(names, '同名', 'name')}
      </ul>
      <div class="board-note muted">
        录监护人或考勤时填的是<strong>学生姓名</strong>，重名系统分不清是哪一个，
        会直接报错让你确认。请把其中一个改成能区分的写法（例如「张伟（大）」）。
        点名单不受影响 —— 它是按学生选的；学号也不会重复，那是数据库唯一索引挡着的。
      </div>
    </div>`;
  },
};

export const studentsPageDef = {
  specKey: 'students',
  group: '学生管理',
  iconName: 'users',
  panel,
  // 行内多一个入口：点开是「一生一档」（考勤/成绩/作业/违纪/谈话/家访/资助一眼看完）
  rowActions: [
    {
      name: 'archive',
      label: '档案',
      async run(row) {
        await openStudentArchive(row);
      },
    },
    {
      name: 'comment',
      label: '评语',
      async run(row) {
        await openCommentDraft(row);
      },
    },
  ],
};
