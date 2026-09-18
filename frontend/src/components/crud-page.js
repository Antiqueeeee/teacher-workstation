/**
 * 通用列表页：完全由注册表的声明驱动，页面自身几乎不写代码。
 *
 * 两条从旧应用教训里来的纪律：
 * 1. **筛选/搜索只重绘列表区，不整页重绘** —— 旧应用每次操作都整页 rerender，
 *    输入框被重建，打字打到一半焦点就丢。
 * 2. **软删除必须有出口** —— 列表里能勾「显示已删除」，已删记录带恢复按钮；
 *    否则「删除后可以找回」就是一句空话（评审抓到过这个问题）。
 */

import { api, triggerDownload } from '../core/api.js';
import { esc } from '../core/dom.js';
import { cellValue, DASH, text } from '../core/format.js';
import { icon } from '../core/icons.js';
import { getListState, toParams } from '../core/store.js';
import { openForm } from './form.js';
import { openImport } from './import-modal.js';
import { openMediaPanel } from './media-picker.js';
import { confirmBox, toast } from './ui.js';

const PAGE_SIZES = [20, 50, 100];
const SEARCH_DEBOUNCE = 300;

/* ---------------------------------------------------------------- 渲染片段 */

function filterOptions(field) {
  if (field.options?.length) return field.options;
  if (field.type === 'checkbox') return ['是', '否'];
  return [];
}

function toolbarHtml(spec, state, actions) {
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

  const actionButtons = actions
    .map(
      (action) =>
        `<button class="btn${action.primary ? ' btn-primary' : ''}" type="button" data-page-action="${esc(action.name)}">${icon(action.iconName || 'check', 16)} ${esc(action.label)}</button>`,
    )
    .join('');
  // 页面自己带主操作（如出勤的「点名」）时，「新增」退成次要按钮，避免两个蓝按钮打架
  const newClass = actions.some((action) => action.primary) ? 'btn' : 'btn-primary';

  return `
    <div class="toolbar">
      <input class="input search" type="search" placeholder="搜索…" value="${esc(state.q)}" data-search>
      ${filters}
      ${actionButtons}
      <button class="btn ${newClass}" type="button" data-new>${icon('plus', 16)} 新增</button>
      <button class="btn" type="button" data-import>${icon('import', 16)} 导入</button>
      <button class="btn" type="button" data-export>${icon('export', 16)} 导出</button>
      <a class="btn" href="${api.templateUrl(spec.key)}" download title="下载导入模板">${icon('template', 16)} 模板</a>
      ${
        spec.softDelete
          ? `<label class="checkbox-row" title="删除的记录会保留在库里，勾选后才能看到并恢复">
        <input type="checkbox" data-show-deleted${state.includeDeleted ? ' checked' : ''}>
        <span class="muted">显示已删除</span>
      </label>`
          : ''
      }
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

function rowActions(row, spec, extra = []) {
  if (row.deleted_at) {
    return `<button class="btn btn-sm" type="button" data-restore="${row.id}">恢复</button>`;
  }
  // 页面自己声明的行内动作（例如学生档案的「一生一档」）
  const custom = extra
    .map(
      (action) =>
        `<button class="btn btn-sm" type="button" data-row-action="${esc(action.name)}"
           data-row-id="${row.id}">${esc(action.label)}</button>`,
    )
    .join('');
  // 支持附件的表（沟通留档类）多一个入口：照片与录音归档都在里面
  const media = spec.mediaOwner
    ? `<button class="btn btn-sm" type="button" data-media="${row.id}"
         title="照片与录音归档">附件${row.attachment_count ? ` ${row.attachment_count}` : ''}</button>`
    : '';
  return `${custom}${media}
    <button class="btn btn-sm" type="button" data-edit="${row.id}">编辑</button>
    <button class="btn btn-sm btn-ghost" type="button" data-del="${row.id}">删除</button>`;
}

function deletedBadge(row) {
  return row.deleted_at ? '<span class="badge badge-rose">已删除</span> ' : '';
}

function tableHtml(spec, rows, state, extraActions) {
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
        <td class="actions">${deletedBadge(row)}${rowActions(row, spec, extraActions)}</td>
      </tr>`;
    })
    .join('');

  return `
    <div class="table-wrap only-wide">
      <table class="table">
        <thead><tr>${head}<th style="width:140px"></th></tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>`;
}

/** 窄屏卡片视图：一行信息读完，动作按钮放在卡片底部（拇指够得到）。 */
function cardsHtml(spec, rows, extraActions = []) {
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
              ${deletedBadge(row)}
            </div>
            ${details}
            <div class="toolbar" style="margin:10px 0 0">${rowActions(row, spec, extraActions)}</div>
          </div>`;
        })
        .join('')}
    </div>`;
}

function listHtml(spec, rows, meta, state, extraActions = []) {
  if (!rows.length) {
    const filtered = state.q || Object.values(state.filters || {}).some(Boolean);
    return `<div class="empty">
      <strong>${filtered ? '没有符合条件的记录' : `还没有${esc(spec.entity)}`}</strong>
      ${filtered ? '试试清空搜索词或筛选条件。' : '点上面的「新增」开始记，或把已有的表格「导入」进来。'}
    </div>`;
  }
  const pages = Math.max(1, Math.ceil(meta.total / meta.pageSize));
  return `
    ${tableHtml(spec, rows, state, extraActions)}
    ${cardsHtml(spec, rows, extraActions)}
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

export function createCrudPage({
  specKey,
  spec,
  group,
  iconName = 'list',
  actions = [],
  panel = null,
  rowActions: rowActionsDef = [],
}) {
  if (!spec) throw new Error(`页面 ${specKey} 找不到对应的表声明：注册表里没有 ${specKey}`);

  const state = getListState(spec);
  let rowsById = new Map();
  // 当前页面的根节点：render 时还没有，bind 之后才有。
  // 看板要能自己触发重绘，所以按需取，而不是在 render 时捕获一个还不存在的节点
  let host = null;

  const params = () => toParams(state);
  const context = () => ({ spec, state, params, refresh });

  /** 重绘看板区（如果有）—— 点名存完要让出勤率立刻更新，而不是等用户手动刷新 */
  async function refreshPanel() {
    if (!panel || !host) return;
    const area = host.querySelector('[data-panel]');
    if (area) area.innerHTML = await panel.html(context());
  }

  async function refresh() {
    await refreshPanel();
    if (host) await refreshList(host);
  }

  async function loadStats() {
    try {
      return await api.stats(spec.key, params());
    } catch {
      return null; // 统计失败不该让整个页面打不开
    }
  }

  /**
   * 只重绘列表区：输入框、筛选下拉都不重建，所以打字不会丢焦点。
   * 失败要**明确告知并保留原内容** —— 曾经的写法是静默失败：
   * 翻页/切筛选点了没反应、不报错、内容还是旧的。
   */
  async function refreshList(root) {
    const area = root.querySelector('[data-list]');
    try {
      const list = await api.list(spec.key, params());
      rowsById = new Map(list.rows.map((row) => [String(row.id), row]));
      area.innerHTML = listHtml(spec, list.rows, list.meta, state, rowActionsDef);
      const kpi = root.querySelector('[data-kpi]');
      const stats = await loadStats();
      if (kpi && stats) kpi.innerHTML = kpiHtml(spec, stats);
    } catch (error) {
      toast(error.message, 'err', 7000);
    }
  }

  function bindEvents(root) {
    let timer = null;
    host = root;
    if (panel?.bind) panel.bind(root, context());

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
      if (target.matches('[data-show-deleted]')) {
        state.includeDeleted = target.checked;
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
        if (saved) refresh();
        return;
      }

      // 注意选择器是 data-page-action 而不是 data-action：
      // 错误卡片上的「重试」按钮用的是 data-action，两者混用会让重试按钮点了没反应
      const actionButton = target.closest('[data-page-action]');
      if (actionButton) {
        const action = actions.find((item) => item.name === actionButton.dataset.pageAction);
        if (action) await action.run(context());
        return;
      }

      const rowAction = target.closest('[data-row-action]');
      if (rowAction) {
        const action = rowActionsDef.find((item) => item.name === rowAction.dataset.rowAction);
        if (action) {
          await action.run(rowsById.get(rowAction.dataset.rowId), context());
        }
        return;
      }

      const media = target.closest('[data-media]');
      if (media) {
        const row = rowsById.get(media.dataset.media);
        openMediaPanel({
          ownerTable: spec.key,
          ownerId: media.dataset.media,
          title: row?.[spec.columns[0].k] ? String(row[spec.columns[0].k]) : spec.entity,
          onChanged: refresh,
        });
        return;
      }

      const edit = target.closest('[data-edit]');
      if (edit) {
        const saved = await openForm(spec, rowsById.get(edit.dataset.edit));
        if (saved) refresh();
        return;
      }

      const restore = target.closest('[data-restore]');
      if (restore) {
        try {
          await api.restore(spec.key, restore.dataset.restore);
          toast('已恢复');
          refreshList(root);
        } catch (error) {
          toast(error.message, 'err', 6000);
        }
        return;
      }

      const del = target.closest('[data-del]');
      if (del) {
        const row = rowsById.get(del.dataset.del);
        const label = text(row?.[spec.columns[0].k]);
        // 文案必须与真实行为一致：软删除才说「可以找回」
        const message = spec.softDelete
          ? `确定删除「${esc(label)}」吗？删除后记录仍留在库里，勾选工具栏的「显示已删除」可以恢复。`
          : `确定删除「${esc(label)}」吗？这条记录会被<strong>彻底删掉</strong>，不能恢复。`;
        const yes = await confirmBox(message, { okText: '删除', danger: true });
        if (!yes) return;
        try {
          await api.remove(spec.key, del.dataset.del);
          toast(spec.softDelete ? '已删除，可在「显示已删除」里恢复' : '已删除');
          refresh();
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
      const [list, stats, panelHtml] = await Promise.all([
        api.list(spec.key, params()),
        loadStats(),
        // 看板初始内容与列表一起取：两处显示的必须是同一时刻的数据
        panel ? panel.html(context()) : Promise.resolve(''),
      ]);
      rowsById = new Map(list.rows.map((row) => [String(row.id), row]));
      return {
        html: `
          <div data-kpi>${kpiHtml(spec, stats)}</div>
          ${panelHtml ? `<div data-panel>${panelHtml}</div>` : ''}
          ${toolbarHtml(spec, state, actions)}
          <div data-list>${listHtml(spec, list.rows, list.meta, state, rowActionsDef)}</div>`,
        bind: (root) => bindEvents(root),
      };
    },
  };
}
