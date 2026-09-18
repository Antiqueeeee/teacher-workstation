/**
 * 点名弹窗：一天一次、整批提交。
 *
 * 与旧应用的点名（`:9946`）差在三处，都是那边的真实毛病：
 * 1. **五种状态都能标**（旧应用的选项只有「正常/迟到/病假/事假/旷课」，早退根本标不了，
 *    而提交时的清理名单也漏了早退 —— 于是早退记录永远删不掉）；
 * 2. **保存按整体覆盖**：回到「正常」的学生，当天记录会被清掉，不残留；
 * 3. **界面不覆盖手工填的东西**：状态没变的那条，后端一个字都不动。
 *    这里也会把已有的事由/处理情况显示出来，让老师知道那内容还在。
 *
 * 数据流上有一条纪律：**选中项存在 JS 里，不在 DOM 里**。
 * 所以「找学生」输入框可以边打边筛，不会因为重绘列表而丢焦点
 * （旧应用每次操作整页 rerender，输入到一半焦点就没了）。
 */

import { api } from '../core/api.js';
import { esc } from '../core/dom.js';
import { errorCard } from '../core/errors.js';
import { todayISO } from '../core/format.js';
import { getSpec } from '../core/store.js';
import { closeModal, confirmBox, openModal, toast } from './ui.js';

/**
 * 状态词表来自**后端注册表**（`attendance.type` 字段的 options）。
 *
 * 不在前端再抄一份：抄一份就是两处描述同一件事，迟早对不上 ——
 * 而这里的「对不上」意味着老师能选到一个后端不认的状态。
 * 必须在 `openRollCall` 里现取（模块被 import 时注册表还没拉回来）。
 */
function typeOptions() {
  const field = getSpec('attendance')?.fields.find((item) => item.k === 'type');
  if (!field?.options?.length) {
    throw new Error('注册表里没有考勤类型词表（attendance.type），请刷新页面重试。');
  }
  return field.options;
}

function optionsHtml(current, types) {
  // 空串表示「正常」——正常不落记录
  return ['', ...types]
    .map(
      (value) =>
        `<option value="${esc(value)}"${current === value ? ' selected' : ''}>${value ? esc(value) : '正常'}</option>`,
    )
    .join('');
}

function rowHtml(item, current, types) {
  const note = [item.reason, item.handledNote].filter(Boolean).join(' · ');
  return `<div class="roll-row">
    <div class="roll-body">
      <div class="roll-name">${esc(item.studentName)}<span class="muted">${esc(item.sno || '')}</span></div>
      ${note ? `<div class="roll-note">已有：${esc(note)}</div>` : ''}
    </div>
    <select class="select" data-student="${item.studentId}" aria-label="${esc(item.studentName)}">${optionsHtml(current, types)}</select>
  </div>`;
}

function changesText(changes) {
  const parts = [];
  if (changes.created) parts.push(`新增 ${changes.created}`);
  if (changes.updated) parts.push(`修改 ${changes.updated}`);
  if (changes.removed) parts.push(`清除 ${changes.removed}`);
  return parts.length ? `已保存：${parts.join('、')}` : '已保存：当天状态没有变化';
}

export async function openRollCall({ classId, day, onSaved } = {}) {
  let currentDay = day || todayISO();
  let view = null;
  const selected = new Map(); // studentId -> 类型（'' = 正常）
  let keyword = '';

  openModal({
    title: '点名',
    wide: true,
    body: `
      <div class="roll-head">
        <input class="input" type="date" data-day value="${esc(currentDay)}">
        <input class="input search" type="search" placeholder="找学生…" data-roll-search>
        <button class="btn btn-sm" type="button" data-all-normal>全部正常</button>
      </div>
      <div class="roll-hint muted" data-roll-hint></div>
      <div class="roll-list" data-roll-list><div class="muted">正在载入…</div></div>`,
    footer: `
      <span class="muted" style="margin-right:auto">状态没变的记录不会被改动</span>
      <button class="btn" type="button" data-cancel>取消</button>
      <button class="btn btn-primary" type="button" data-save>保存当天考勤</button>`,
    onMount(root) {
      const listArea = root.querySelector('[data-roll-list]');
      const hintArea = root.querySelector('[data-roll-hint]');
      const dateInput = root.querySelector('[data-day]');
      const searchInput = root.querySelector('[data-roll-search]');
      const saveButton = root.querySelector('[data-save]');
      root.querySelector('[data-cancel]').addEventListener('click', closeModal);

      let types;
      try {
        types = typeOptions();
      } catch (error) {
        listArea.innerHTML = errorCard(error);
        return;
      }

      /** 界面上有没有没保存的改动 —— 换日期前要问一声，免得悄悄丢掉 */
      function dirty() {
        if (!view) return false;
        return view.students.some((item) => (selected.get(item.studentId) || '') !== (item.type || ''));
      }

      function hintHtml() {
        const marked = view.students.filter((item) => selected.get(item.studentId)).length;
        return `${esc(currentDay)} · 全班 ${view.students.length} 人 · 已标记 ${marked} 人
          ${view.summary.registered ? '' : '（这天还没登记过考勤）'}`;
      }

      function renderList() {
        const items = view.students.filter(
          (item) =>
            !keyword ||
            item.studentName.includes(keyword) ||
            String(item.sno || '').includes(keyword),
        );
        listArea.innerHTML = items.length
          ? items.map((item) => rowHtml(item, selected.get(item.studentId) || '', types)).join('')
          : '<div class="empty">没有匹配的学生</div>';
        hintArea.innerHTML = hintHtml();
      }

      async function load() {
        listArea.innerHTML = '<div class="muted">正在载入…</div>';
        hintArea.textContent = '';
        try {
          view = await api.attendanceDay(currentDay, classId);
        } catch (error) {
          listArea.innerHTML = errorCard(error);
          return;
        }
        selected.clear();
        for (const item of view.students) selected.set(item.studentId, item.type || '');
        renderList();
      }

      async function switchDay(next) {
        if (!next || next === currentDay) return;
        if (dirty()) {
          const yes = await confirmBox('换日期会丢掉这次还没保存的改动，继续吗？', {
            okText: '丢掉并换日期',
            danger: true,
          });
          if (!yes) {
            dateInput.value = currentDay; // 界面上的日期退回去，别显示成一个假的
            return;
          }
        }
        currentDay = next;
        await load();
      }

      dateInput.addEventListener('change', () => switchDay(dateInput.value));

      searchInput.addEventListener('input', () => {
        keyword = searchInput.value.trim();
        renderList();
      });

      root.querySelector('[data-all-normal]').addEventListener('click', () => {
        if (!view) return; // 还没载入成功（或载入失败）时按钮不该炸
        for (const item of view.students) selected.set(item.studentId, '');
        renderList();
      });

      listArea.addEventListener('change', (event) => {
        const select = event.target.closest('[data-student]');
        if (!select) return;
        selected.set(Number(select.dataset.student), select.value);
        hintArea.innerHTML = hintHtml();
      });

      saveButton.addEventListener('click', async () => {
        if (!view) return;
        const entries = view.students
          .filter((item) => selected.get(item.studentId))
          .map((item) => ({ studentId: item.studentId, type: selected.get(item.studentId) }));

        saveButton.disabled = true;
        try {
          const data = await api.saveAttendanceDay({ date: currentDay, classId, entries });
          toast(changesText(data.changes));
          closeModal();
          if (onSaved) onSaved();
        } catch (error) {
          // 保存失败**不关弹窗**：老师的勾选还在，改完能直接重试
          toast(error.message, 'err', 7000);
        } finally {
          saveButton.disabled = false;
        }
      });

      load();
    },
  });
}
