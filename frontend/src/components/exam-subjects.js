/**
 * 「这场考试考哪几科、每科满分多少」的编辑弹窗。
 *
 * 这是旧应用「各科满分设置」的替代：那边是一个全局配置（改了一次所有考试一起变），
 * 这里挂在**具体某一场考试**上 —— 因为「本场满分」就是及格线的分母，
 * 而单元测与期末考的满分本来就不一样，全局一个值表达不了。
 *
 * 科目清单只有这一处能改：成绩录入表的列、及格线的分母、报表的统计范围全部读它。
 * 全部可选科目（用来把删掉的科目加回来）由接口一并给出，前端不自己维护词表。
 */

import { api } from '../core/api.js';
import { esc } from '../core/dom.js';
import { errorCard } from '../core/errors.js';
import { closeModal, openModal, toast } from './ui.js';

function rowHtml(subject, checked, fullMarks) {
  return `<div class="subject-row">
    <label class="checkbox-row">
      <input type="checkbox" data-here="${esc(subject)}"${checked ? ' checked' : ''}>
      <span>${esc(subject)}</span>
    </label>
    <input class="input" type="number" min="1" max="1000" data-full="${esc(subject)}"
      value="${fullMarks}"${checked ? '' : ' disabled'}>
  </div>`;
}

export async function openExamSubjects({ examId, examName, onSaved } = {}) {
  openModal({
    title: `科目与满分 · ${esc(examName || '')}`,
    body: `<div data-subjects><div class="muted">正在载入…</div></div>
      <div class="muted" style="margin-top:10px">
        及格线按<strong>本场考的这些科目</strong>的满分算，不再按全部科目算。
        已有成绩的科目取消勾选会被拒绝，并告诉你有多少条成绩 —— 免得数据被悄悄删掉。
      </div>`,
    footer: `
      <button class="btn" type="button" data-cancel>取消</button>
      <button class="btn btn-primary" type="button" data-save>保存</button>`,
    onMount(root) {
      const area = root.querySelector('[data-subjects]');
      const saveButton = root.querySelector('[data-save]');
      root.querySelector('[data-cancel]').addEventListener('click', closeModal);

      function collect() {
        const subjects = [];
        area.querySelectorAll('[data-here]').forEach((box) => {
          if (!box.checked) return;
          const field = area.querySelector(`[data-full="${CSS.escape(box.dataset.here)}"]`);
          subjects.push({ subject: box.dataset.here, fullMarks: Number(field.value || 0) });
        });
        return subjects;
      }

      function load() {
        area.innerHTML = '<div class="muted">正在载入…</div>';
        api
          .scoreSheet(examId)
          .then((sheet) => {
            const full = new Map(sheet.subjects.map((item) => [item.subject, item.fullMarks]));
            area.innerHTML = sheet.allSubjects
              .map((subject) => rowHtml(subject, full.has(subject), full.get(subject) ?? 100))
              .join('');
            // 勾选状态一变就放开/锁住对应的满分输入框：没勾的科目不该还能改满分
            area.querySelectorAll('[data-here]').forEach((box) => {
              box.addEventListener('change', () => {
                const field = area.querySelector(`[data-full="${CSS.escape(box.dataset.here)}"]`);
                field.disabled = !box.checked;
                if (box.checked && !field.value) field.value = 100;
              });
            });
          })
          .catch((error) => {
            area.innerHTML = errorCard(error);
          });
      }

      saveButton.addEventListener('click', async () => {
        const subjects = collect();
        if (!subjects.length) {
          toast('至少要留一个科目', 'err', 5000);
          return;
        }
        saveButton.disabled = true;
        try {
          await api.saveExamSubjects(examId, subjects);
          toast('已保存');
          closeModal();
          if (onSaved) onSaved();
        } catch (error) {
          // 被拒绝时（例如某科已有成绩）**不关弹窗**：勾选还在，改完能直接重试
          toast(error.message, 'err', 8000);
        } finally {
          saveButton.disabled = false;
        }
      });

      load();
    },
  });
}
