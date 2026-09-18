/**
 * 导入弹窗：选文件 → 预览（下一步会写什么、哪一行有问题）→ 确认写入。
 *
 * 预览是**必须**的一步，不是装饰：老师的表格里总有陈旧或手写的格子，
 * 直接导入的后果是「数据错得悄无声息」。所以这里把每一行的值和问题都摆出来，
 * 有问题就不给提交按钮 —— 逼一次人工确认，换掉后面几小时的排查。
 */

import { api } from '../core/api.js';
import { esc } from '../core/dom.js';
import { toast, openModal, closeModal } from './ui.js';

const PREVIEW_LIMIT = 30; // 预览只展示前若干行，避免弹窗被几百行撑爆

function summaryChips(summary) {
  return `
    <span class="badge badge-ice">共 ${summary.total} 行</span>
    <span class="badge badge-mint">可导入 ${summary.ok}</span>
    ${summary.problem ? `<span class="badge badge-rose">有问题 ${summary.problem}</span>` : ''}
    ${summary.duplicateInFile ? `<span class="badge badge-sun">文件内重复 ${summary.duplicateInFile}</span>` : ''}`;
}

function rowsHtml(spec, preview) {
  const columns = spec.fields.filter((field) => field.editable).slice(0, 4);
  const body = preview.rows.slice(0, PREVIEW_LIMIT).map((row) => {
    const cells = columns
      .map((field) => {
        const bad = row.issues.find((issue) => issue.field === field.k);
        const value = row.values[field.k];
        return `<td class="${bad ? 'cell-bad' : ''}" title="${esc(bad ? bad.message : value)}">${esc(value ?? '')}</td>`;
      })
      .join('');
    const rowIssue = row.issues.find((issue) => !issue.field);
    return `<tr class="${row.ok ? '' : 'row-bad'}">
      <td class="num">${row.row}</td>${cells}
      <td>${rowIssue ? `<span class="badge badge-rose">${esc(rowIssue.message)}</span>` : '<span class="badge badge-mint">可导入</span>'}</td>
    </tr>`;
  });
  const more =
    preview.rows.length > PREVIEW_LIMIT
      ? `<p class="muted">仅显示前 ${PREVIEW_LIMIT} 行，共 ${preview.rows.length} 行。</p>`
      : '';
  return `
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>行号</th>${columns.map((f) => `<th>${esc(f.label)}</th>`).join('')}<th>状态</th></tr></thead>
        <tbody>${body.join('')}</tbody>
      </table>
    </div>${more}`;
}

function noticesHtml(preview) {
  const parts = [];
  if (preview.missingColumns?.length) {
    parts.push(`<div class="notice">表里没有这些必填列：${esc(preview.missingColumns.join('、'))}。请下载模板对照列名。</div>`);
  }
  if (preview.unknownHeaders?.length) {
    parts.push(`<div class="notice">这些列没认出来，会被忽略：${esc(preview.unknownHeaders.join('、'))}。</div>`);
  }
  if (preview.summary.problem) {
    // 预览只显示前若干行，所以必须把**问题行号**直接列出来 ——
    // 否则「见下方红字」会指向用户根本看不到的地方
    const problemRows = preview.rows
      .filter((row) => !row.ok)
      .map((row) => row.row)
      .slice(0, 12)
      .join('、');
    const more = preview.summary.problem > 12 ? ` 等（共 ${preview.summary.problem} 行）` : '';
    parts.push(
      `<div class="notice">有 ${preview.summary.problem} 行没通过校验：第 ${problemRows} 行${more}。请先在表格里改好再重新上传 —— 整批要么全进、要么全不进，不会进一半。</div>`,
    );
  }
  return parts.join('');
}

export function openImport(spec, onDone) {
  openModal({
    title: `导入${spec.entity}`,
    wide: true,
    body: `
      <div class="toolbar">
        <input type="file" id="import-file" accept=".xlsx,.xlsm,.csv,.txt">
        <a class="btn btn-sm" href="${api.templateUrl(spec.key)}" download>下载导入模板</a>
      </div>
      <p class="muted">支持 Excel（.xlsx）与 CSV。列名可以和你手里的表不一样，常见的写法都能认出来（如「内容 / 事项 / 具体内容」）。</p>
      <div id="import-result"></div>`,
    onMount(root) {
      const result = root.querySelector('#import-result');
      const picker = root.querySelector('#import-file');

      picker.addEventListener('change', async () => {
        const file = picker.files?.[0];
        if (!file) return;
        result.innerHTML = '<div class="empty">正在解析…</div>';
        let preview;
        try {
          preview = await api.importPreview(spec.key, file);
        } catch (error) {
          result.innerHTML = `<div class="notice">${esc(error.message)}</div>`;
          return;
        }

        const canCommit = preview.summary.problem === 0 && preview.summary.ok > 0;
        result.innerHTML = `
          <div class="import-summary">${summaryChips(preview.summary)}</div>
          ${noticesHtml(preview)}
          ${rowsHtml(spec, preview)}
          <div class="modal-foot" style="border:0;padding:12px 0 0">
            <button class="btn btn-primary" type="button" data-commit ${canCommit ? '' : 'disabled'}>
              确认导入 ${preview.summary.ok} 行
            </button>
          </div>`;

        const commit = result.querySelector('[data-commit]');
        commit?.addEventListener('click', async () => {
          commit.disabled = true;
          commit.textContent = '写入中…';
          try {
            const rows = preview.rows.filter((row) => row.ok).map((row) => row.values);
            const summary = await api.importCommit(spec.key, rows);
            closeModal();
            toast(
              summary.skippedCount
                ? `已导入 ${summary.created} 行，跳过 ${summary.skippedCount} 行重复记录`
                : `已导入 ${summary.created} 行`,
            );
            onDone?.();
          } catch (error) {
            commit.disabled = false;
            commit.textContent = '确认导入';
            toast(error.message, 'err', 7000);
          }
        });
      });
    },
  });
}
