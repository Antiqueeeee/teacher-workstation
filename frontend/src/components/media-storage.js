/**
 * 存储占用与清理。
 *
 * 顺手补上 `04` §3.5 要求的那个入口：录音留档涉及隐私，「建议沟通结束后 3 个月内清理」
 * 这句话必须配一个**做得到**的按钮，否则只是一句免责声明。
 *
 * 清理是**真正删文件**的动作（不是进回收站），所以：
 * - 默认只清录音，不动照片；
 * - 可以只清某一个学生的（对应「学生毕业/转出」）；
 * - 提交前把「会删掉多少」说清楚。
 */

import { api } from '../core/api.js';
import { esc } from '../core/dom.js';
import { closeModal, confirmBox, openModal, toast } from './ui.js';

function sizeText(bytes) {
  let size = Number(bytes || 0);
  for (const unit of ['B', 'KB', 'MB', 'GB']) {
    if (size < 1024 || unit === 'GB') return unit === 'B' ? `${size} B` : `${size.toFixed(1)} ${unit}`;
    size /= 1024;
  }
  return `${size.toFixed(1)} GB`;
}

function statsHtml(stats) {
  return `<div class="kpi-row" style="margin:0 0 12px">
    <div class="kpi"><div class="kpi-value">${sizeText(stats.media)}</div>
      <div class="kpi-label">照片与音视频（${stats.mediaCount} 个文件）</div></div>
    <div class="kpi"><div class="kpi-value">${sizeText(stats.thumbs)}</div><div class="kpi-label">缩略图</div></div>
    <div class="kpi"><div class="kpi-value">${sizeText(stats.trash)}</div><div class="kpi-label">回收站</div></div>
    <div class="kpi"><div class="kpi-value">${sizeText(stats.database)}</div><div class="kpi-label">数据库</div></div>
  </div>
  <div class="muted">数据目录：<code>${esc(stats.dataDir)}</code>（整个目录拷走就是一份完整备份）</div>`;
}

export function openStoragePanel({ classId } = {}) {
  openModal({
    title: '存储占用与清理',
    body: `<div data-stats><div class="muted">正在统计…</div></div>
      <hr style="margin:14px 0;border:0;border-top:1px solid var(--border)">
      <div class="form-grid">
        <div class="field"><label>清理哪一天之前的</label>
          <input class="input" type="date" data-before></div>
        <div class="field"><label>只清这个学生的（可留空）</label>
          <input class="input" type="text" data-student placeholder="学生姓名，留空=全班"></div>
        <div class="field full"><label>清理内容</label>
          <select class="select" data-kinds>
            <option value="audio">只清录音（建议）</option>
            <option value="audio,video">录音与视频</option>
            <option value="audio,video,image">录音、视频与照片</option>
          </select>
          <div class="hint">清理是<strong>真正删掉文件</strong>，不进回收站 —— 删了就找不回来了。</div></div>
      </div>`,
    footer: `
      <button class="btn" type="button" data-cancel>关闭</button>
      <button class="btn btn-danger" type="button" data-purge>开始清理</button>`,
    onMount(root) {
      const statsArea = root.querySelector('[data-stats]');
      const before = root.querySelector('[data-before]');

      api
        .mediaStorage()
        .then((stats) => {
          statsArea.innerHTML = statsHtml(stats);
        })
        .catch((error) => {
          statsArea.innerHTML = `<div class="muted">占用没取到：${esc(error.message)}</div>`;
        });

      // 默认给一个「三个月前」的日期 —— 文档里的建议就是这么说的，老师不必自己算
      const cutoff = new Date();
      cutoff.setMonth(cutoff.getMonth() - 3);
      before.value = cutoff.toISOString().slice(0, 10);

      root.querySelector('[data-cancel]').addEventListener('click', closeModal);
      root.querySelector('[data-purge]').addEventListener('click', async () => {
        const day = before.value;
        if (!day) {
          toast('先选一个日期', 'err', 4000);
          return;
        }
        const kinds = root.querySelector('[data-kinds]').value.split(',');
        const who = root.querySelector('[data-student]').value.trim();
        const yes = await confirmBox(
          `清掉 <strong>${esc(day)}</strong> 之前的${who ? `「${esc(who)}」的` : ''}文件？<br><br>
           这是<strong>真正删除文件</strong>（不进回收站），删了找不回来。`,
          { okText: '确认清理', danger: true },
        );
        if (!yes) return;
        try {
          const result = await api.mediaPurge({
            classId,
            before: day,
            kinds,
            studentId: who ? await findStudentId(who) : null,
          });
          toast(result.removed ? `已清理 ${result.removed} 个文件` : '没有符合条件的文件');
          const stats = await api.mediaStorage();
          statsArea.innerHTML = statsHtml(stats);
        } catch (error) {
          toast(error.message, 'err', 8000);
        }
      });
    },
  });
}

/** 老师填的是姓名，这里解析成 id；查不到就说清，别静默按全班清。 */
async function findStudentId(name) {
  const list = await api.list('students', { q: name, pageSize: 20 });
  const match = list.rows.filter((row) => row.name === name);
  if (match.length !== 1) {
    throw new Error(
      match.length ? `有 ${match.length} 个学生叫「${name}」，请用学号或先处理重名` : `学生档案里没有叫「${name}」的学生`,
    );
  }
  return match[0].id;
}
