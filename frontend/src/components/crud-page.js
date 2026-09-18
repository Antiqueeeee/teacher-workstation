/**
 * 通用列表页：完全由注册表的声明驱动，页面自身几乎不写代码。
 *
 * 一条来自旧应用教训的纪律：**筛选/搜索只重绘列表区，不整页重绘**。
 * 旧应用每次操作都整页 rerender，输入框被重建 —— 打字打到一半焦点就丢了。
 * 这里把「查询条件」放在内存、把「列表区」做成独立容器，输入框全程不重建。
 */

import { api, triggerDownload } from '../core/api.js';
import { esc } from '../core/dom.js';
import { cellValue, DASH, text } from '../core/format.js';
import { icon } from '../core/icons.js';
import { getListState, getSpec, toParams } from '../core/store.js';
import { openForm } from './form.js';
import { openImport } from './import-modal.js';
import { confirmBox, toast } from './ui.js';

const PAGE_SIZES = [20, 50, 100];
const SEARCH_DEBOUNCE = 300;

/* ---------------------------------------------------------------- 渲染片段 */

function filterOptions(field) {
  if (field.options?.length) return field.options;
  if (field.type === 'checkbox') return ['是', '否'];
  return [];
}

function toolbarHtml(spec, state) {
  const filters = spec.filterKeys
    .map((key) => {
      const field = spec.fields.find((item) => item.k === key);
      if (!field) return '';
      const options = filterOptions(field);
      if (!options.length) return '';
      const current = state.filters[key] || '';
      return `<select class="select" style="width:auto" data-filter="${esc(key)}">
        <option value="">${esc(field.label)}（全部）</option>
        ${options
          .map(
            (option) =>
              `<option value="${esc(option)}"${current === option ? ' selected' : ''}>${esc(option)}</option>`,
          )
          .join('')}
      </select>`;
    })
    .join('');

  return `
    <div class="toolbar">
      <input class="input search" type="search" placeholder="搜索…" value="${esc(state.q)}" data-search>
      ${filters}
      <button class="btn btn-primary" type="button" data-new>${icon('plus', 16)} 新增</button>
      <button class="btn" type="button" data-import>${icon('import', 16)} 导入</button>
      <button class="btn" type="button" data-export>${icon('export', 16)} 导出</button>
      <a class="btn" href="${api.templateUrl(spec.key)}" download title="下载导入模板">${icon('template', 16)} 模板</a>
    </div>`;
}

function kpiHtml(spec, stats) {
  if (!stats) return '';
  const chips = [];
  for (const key of spec.filterKeys) {
    const buckets = stats.groups?.[key] || {};
    const entries = Object.entries(buckets);
    if (!entries.length) continue;
    const field = spec.fields.find((item) => item.k === key);
    chips.push(
      `<div class="kpi">
        <div class="kpi-label">${esc(field?.label || key)}</div>
        <div class="muted">${entries
          .map(([value, count]) => `${esc(value || '未填')} ${count}`)
          .join(' · ')}</div>
      </div>`,
    );
  }
  return `
    <div class="kpi-row">
      <div class="kpi"><div class="kpi-value">${stats.total}</div><div class="kpi-label">共 ${esc(spec.entity)}</div></div>
      ${chips.join('')}
    </div>`;
}

function sortMark(state, key) {
  if (state.sort !== key) return '';
  return `<span class="sort-mark">${state.dir === 'asc' ? '▲' : '▼'}</span>`;
}

function tableHtml(spec, rows, state) {
  const head = spec.columns
    .map((column) =>
      column.sortable
        ? `<th class="sortable" data-sort="${esc(column.k)}" style="width:${esc(column.w || 'auto')}">
             ${esc(column.label)} ${sortMark(state, column.k)}
           </th>`
        : `<th>${esc(column.label)}</th>`,
    )
    .join('');

  const body = rows
    .map((row) => {
      const cells = spec.columns
        .map((column) => {
          const field = spec.fields.find((item) => item.k === column.k);
          const value = cellValue(field, row[column.k]);
          return `<td class="${column.numeric ? 'num' : ''}" title="${esc(row[column.k])}">${esc(value)}</td>`;
        })
        .join('');
      return `<tr>
        ${cells}
        <td class="actions">
          <button class="btn btn-sm" type="button" data-edit="${row.id}">编辑</button>
          <button class="btn btn-sm btn-ghost" type="button" data-del="${row.id}">删除</button>
        </td>
      </tr>`;
    })
    .join('');

  return `
    <div class="table-wrap only-wide">
      <table class="table">
        <thead><tr>${head}<th style="width:130px"></th></tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>`;
}

/** 窄屏卡片视图：手机上一行信息读完，动作按钮放在卡片底部（拇指够得到）。 */
function cardsHtml(spec, rows) {
  const [primary, ...rest] = spec.columns;
  return `
    <div class="cards only-narrow">
      ${rows
        .map((row) => {
          const details = rest
            .map((column) => {
              const field = spec.fields.find((item) => item.k === column.k);
              const value = cellValue(field, row[column.k]);
              if (value === DASH) return '';
              return `<div class="row"><span class="k">${esc(column.label)}</span><span>${esc(value)}</span></div>`;
            })
            .join('');
          return `<div class="person-card">
            <div class="card-head">
              <strong>${esc(cellValue(spec.fields.find((f) => f.k === primary.k), row[primary.k]))}</strong>
            </div>
            ${details}
            <div class="toolbar" style="margin:10px 0 0">
              <button class="btn btn-sm" type="button" data-edit="${row.id}">编辑</button>
              <button class="btn btn-sm btn-ghost" type="button" data-del="${row.id}">删除</button>
            </div>
          </div>`;
        })
        .join('')}
    </div>`;
}

function listHtml(spec, rows, meta, state) {
  if (!rows.length) {
    const filtered = state.q || Object.values(state.filters || {}).some(Boolean);
    return `<div class="empty">
      <strong>${filtered ? '没有符合条件的记录' : `还没有${esc(spec.entity)}`}</strong>
      ${filtered ? '试试清空搜索词或筛选条件。' : `点上面的「新增」开始记，或把已有的表格「导入」进来。`}
    </div>`;
  }
  const pages = Math.max(1, Math.ceil(meta.total / meta.pageSize));
  return `
    ${tableHtml(spec, rows, state)}
    ${cardsHtml(spec, rows)}
    <div class="pager">
      <span class="page-info">共 ${meta.total} 条，第 ${meta.page} / ${pages} 页</span>
      <select class="select" style="width:auto" data-page-size>
        ${PAGE_SIZES.map(
          (size) => `<option value="${size}"${size === state.pageSize ? ' selected' : ''}>每页 ${size} 条</option>`,
        ).join('')}
      </select>
      <button class="btn btn-sm" type="button" data-page="prev" ${meta.page <= 1 ? 'disabled' : ''}>上一页</button>
      <button class="btn btn-sm" type="button" data-page="next" ${meta.page >= pages ? 'disabled' : ''}>下一页</button>
    </div>`;
}

/* ---------------------------------------------------------------- 页面工厂 */

export function createCrudPage({ specKey, spec, group, iconName = 'list' }) {
  if (!spec) throw new Error(`页面 ${specKey} 找不到对应的表声明：注册表里没有 ${specKey}`);

  const state = getListState(spec);
  let rowsById = new Map();

  const params = () => toParams(state);

  async function loadStats() {
    try {
      return await api.stats(spec.key, params());
    } catch {
      return null; // 统计失败不该让整个页面打不开
    }
  }

  async function refreshList(root) {
    const area = root.querySelector('[data-list]');
    const list = await api.list(spec.key, params());
    rowsById = new Map(list.rows.map((row) => [String(row.id), row]));
    area.innerHTML = listHtml(spec, list.rows, list.meta, state);
    const kpi = root.querySelector('[data-kpi]');
    const stats = await loadStats();
    if (kpi && stats) kpi.innerHTML = kpiHtml(spec, stats);
  }

  function bindEvents(root) {
    let timer = null;
    root.addEventListener('input', (event) => {
      if (!event.target.matches('[data-search]')) return;
      clearTimeout(timer);
      const value = event.target.value;
      timer = setTimeout(() => {
        state.q = value;
        state.page = 1;
        refreshList(root);
      }, SEARCH_DEBOUNCE);
    });

    root.addEventListener('change', (event) => {
      const target = event.target;
      if (target.matches('[data-filter]')) {
        state.filters[target.dataset.filter] = target.value;
        state.page = 1;
        refreshList(root);
      }
      if (target.matches('[data-page-size]')) {
        state.pageSize = Number(target.value);
        state.page = 1;
        refreshList(root);
      }
    });

    root.addEventListener('click', async (event) => {
      const target = event.target;

      const sortHeader = target.closest('[data-sort]');
      if (sortHeader) {
        const key = sortHeader.dataset.sort;
        state.dir = state.sort === key && state.dir === 'asc' ? 'desc' : 'asc';
        state.sort = key;
        state.page = 1;
        refreshList(root);
        return;
      }

      const pageButton = target.closest('[data-page]');
      if (pageButton) {
        state.page += pageButton.dataset.page === 'next' ? 1 : -1;
        if (state.page < 1) state.page = 1;
        refreshList(root);
        return;
      }

      if (target.closest('[data-new]')) {
        const saved = await openForm(spec);
        if (saved) refreshList(root);
        return;
      }

      const edit = target.closest('[data-edit]');
      if (edit) {
        const saved = await openForm(spec, rowsById.get(edit.dataset.edit));
        if (saved) refreshList(root);
        return;
      }

      const del = target.closest('[data-del]');
      if (del) {
        const row = rowsById.get(del.dataset.del);
        const label = text(row?.[spec.columns[0].k]);
        const yes = await confirmBox(`确定删除「${esc(label)}」吗？删除后可在数据目录里找回（软删除）。`, {
          okText: '删除',
          danger: true,
        });
        if (!yes) return;
        try {
          await api.remove(spec.key, del.dataset.del);
          toast('已删除');
          refreshList(root);
        } catch (error) {
          toast(error.message, 'err', 6000);
        }
        return;
      }

      if (target.closest('[data-import]')) {
        openImport(spec, () => refreshList(root));
        return;
      }

      if (target.closest('[data-export]')) {
        triggerDownload(api.exportUrl(spec.key, params()));
        toast('已按当前筛选导出');
      }
    });
  }

  return {
    key: specKey,
    group,
    icon: iconName,
    title: spec.title,
    async render() {
      const [list, stats] = await Promise.all([api.list(spec.key, params()), loadStats()]);
      rowsById = new Map(list.rows.map((row) => [String(row.id), row]));
      return {
        html: `
          <div data-kpi>${kpiHtml(spec, stats)}</div>
          ${toolbarHtml(spec, state)}
          <div data-list>${listHtml(spec, list.rows, list.meta, state)}</div>`,
        bind: (root) => bindEvents(root),
      };
    },
  };
}
