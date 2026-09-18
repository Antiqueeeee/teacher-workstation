/**
 * 设置：班级信息、存储占用、清空数据。
 *
 * 三条与「不误伤」有关的做法：
 * - 清空数据要**手输「清空」两个字**，不是点一下按钮就执行（不可撤销的操作不该顺手就能点）；
 * - 动手前先列出**每张表会删掉多少行**，让老师看清影响；
 * - **照片与录音默认不动** —— 它们有专门的清理入口（按日期、按学生），
 *   几千张照片删了找不回来，不该混在这个按钮里。
 */

import { api } from '../core/api.js';
import { esc } from '../core/dom.js';
import { errorCard } from '../core/errors.js';
import { store } from '../core/store.js';
import { closeModal, confirmBox, openModal, toast } from '../components/ui.js';

function sizeText(bytes) {
  let size = Number(bytes || 0);
  for (const unit of ['B', 'KB', 'MB', 'GB']) {
    if (size < 1024 || unit === 'GB') return unit === 'B' ? `${size} B` : `${size.toFixed(1)} ${unit}`;
    size /= 1024;
  }
  return `${size.toFixed(1)} GB`;
}

const CLASS_FIELDS = [
  ['name', '班级名称', '如 高二(3)班'],
  ['grade', '年级', '如 高二'],
  ['classNo', '班级序号', '如 3'],
  ['headTeacherName', '班主任', ''],
  ['roomName', '教室', '如 教学楼 305'],
  ['youthBranchName', '团支部名称', '如 高二(3)班团支部'],
];

function formHtml(data) {
  return `<div class="form-grid">${CLASS_FIELDS.map(
    ([key, label, hint]) => `<div class="field">
      <label>${esc(label)}</label>
      <input class="input" data-class="${key}" value="${esc(data[key] || '')}">
      ${hint ? `<div class="hint">${esc(hint)}</div>` : ''}
    </div>`,
  ).join('')}</div>`;
}

export const settingsPage = {
  key: 'settings',
  title: '设置',
  group: '概览',
  icon: 'gear',
  async render() {
    let data;
    try {
      data = await api.settings(store.currentClassId);
    } catch (error) {
      return { html: errorCard(error) };
    }

    const storage = data.storage;
    const rows = data.tableCounts.filter((item) => item.rows > 0);
    const html = `
      <div class="board">
        <div class="board-head"><span class="board-title">班级信息</span>
          <button class="btn btn-sm btn-primary" type="button" data-save-class>保存</button></div>
        ${formHtml(data.class)}
        <div class="muted">这些名字会显示在首页与代课简报上（旧应用是靠「年级 + 班号」拼出来的）。</div>
      </div>

      <div class="board">
        <div class="board-head"><span class="board-title">存储占用</span></div>
        <div class="kpi-row" style="margin:0">
          <div class="kpi"><div class="kpi-value">${sizeText(storage.media)}</div>
            <div class="kpi-label">照片与音视频（${storage.mediaCount} 个文件）</div></div>
          <div class="kpi"><div class="kpi-value">${sizeText(storage.thumbs)}</div><div class="kpi-label">缩略图</div></div>
          <div class="kpi"><div class="kpi-value">${sizeText(storage.trash)}</div><div class="kpi-label">回收站</div></div>
          <div class="kpi"><div class="kpi-value">${sizeText(storage.database)}</div><div class="kpi-label">数据库</div></div>
        </div>
        <div class="muted">数据目录：<code>${esc(storage.dataDir)}</code>
          —— 整个目录拷走就是一份完整备份。清理入口在「家长联系日志」页的「存储与清理」。</div>
      </div>

      <div class="board">
        <div class="board-head"><span class="board-title">这个班现在有多少数据</span></div>
        ${
          rows.length
            ? `<div class="muted">${rows.map((item) => `${esc(item.table)} ${item.rows}`).join(' · ')}</div>`
            : '<div class="muted">还是空的</div>'
        }
      </div>

      <div class="board">
        <div class="board-head"><span class="board-title">清空数据</span>
          <span class="muted">不可撤销</span></div>
        <div class="muted">会清掉这个班的全部业务记录（学生档案、考勤、成绩、沟通留档…），
          <strong>保留班级本身与字段定义</strong>。照片与录音<strong>不动</strong> ——
          要清它们去「存储与清理」，那里能按日期、按学生清。</div>
        <div class="toolbar" style="margin:10px 0 0">
          <button class="btn btn-danger" type="button" data-clear>清空这个班的数据…</button>
        </div>
      </div>`;

    return {
      html,
      bind(root) {
        root.addEventListener('click', async (event) => {
          if (event.target.closest('[data-save-class]')) {
            const payload = {};
            root.querySelectorAll('[data-class]').forEach((input) => {
              payload[input.dataset.class] = input.value;
            });
            try {
              await api.saveClassInfo(payload, store.currentClassId);
              toast('已保存');
            } catch (error) {
              toast(error.message, 'err', 7000);
            }
            return;
          }

          if (event.target.closest('[data-clear]')) {
            openClearDialog(data, () => window.location.reload());
          }
        });
      },
    };
  },
};

function openClearDialog(data, onDone) {
  const rows = data.tableCounts.filter((item) => item.rows > 0);
  openModal({
    title: '清空这个班的数据',
    body: `<div class="archive-alert danger">
        这是<strong>不可撤销</strong>的操作。请先看清会删掉什么：
      </div>
      <div class="muted">${rows.map((item) => `${esc(item.table)} ${item.rows}`).join(' · ') || '（本来就没有数据）'}</div>
      <div class="field" style="margin-top:12px">
        <label>要确认的话，请在下面输入「清空」两个字</label>
        <input class="input" data-confirm placeholder="清空">
      </div>`,
    footer: `
      <button class="btn" type="button" data-cancel>取消</button>
      <button class="btn btn-danger" type="button" data-ok>确认清空</button>`,
    onMount(root) {
      root.querySelector('[data-cancel]').addEventListener('click', closeModal);
      root.querySelector('[data-ok]').addEventListener('click', async () => {
        const word = root.querySelector('[data-confirm]').value.trim();
        if (word !== '清空') {
          toast('请先输入「清空」两个字', 'err', 5000);
          return;
        }
        const yes = await confirmBox('确定清空？数据删了就找不回来了。', {
          okText: '确定清空',
          danger: true,
        });
        if (!yes) return;
        try {
          const result = await api.clearData({ confirm: word, keepMedia: true }, store.currentClassId);
          toast(`已清空 ${result.removed} 条记录（照片与录音保留）`);
          closeModal();
          onDone();
        } catch (error) {
          toast(error.message, 'err', 8000);
        }
      });
    },
  });
}
