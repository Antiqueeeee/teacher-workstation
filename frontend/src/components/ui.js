/**
 * 基础交互：提示条、弹窗、确认框。
 *
 * 全部自己实现、不引库的理由：整个前端没有构建步骤，也没有依赖管理，
 * 引一个 UI 库就意味着要维护一套打包流程 —— 与「老师自己部署」这个前提冲突。
 */

import { qs } from '../core/dom.js';

/* ---------- 提示条 ---------- */

export function toast(message, type = 'ok', timeout = 3600) {
  const host = qs('#toasts');
  if (!host) return;
  const node = document.createElement('div');
  node.className = `toast ${type}`;
  node.textContent = message;
  host.appendChild(node);
  setTimeout(() => node.remove(), timeout);
}

/* ---------- 弹窗 ---------- */

/**
 * 关**最上面**那一层弹窗。
 *
 * 弹窗是**可以叠**的：附件面板里点「删除」会弹确认框、清理面板里点「清理」也是。
 * 早先 `#modal-root.innerHTML = ...` 直接覆盖，于是弹确认框会把原来的面板顶掉 ——
 * 按「取消」面板就没了，按「确认」后写进的是已经脱离 DOM 的节点（统计永远看不到）。
 * 现在每层各有自己的容器，关哪层只影响哪层。
 */
export function closeModal() {
  const root = qs('#modal-root');
  if (!root) return;
  const layers = root.querySelectorAll('.modal-layer');
  if (layers.length) layers[layers.length - 1].remove();
}

export function modalOpen() {
  const root = qs('#modal-root');
  return Boolean(root && root.querySelector('.modal-layer'));
}

/**
 * 打开弹窗（叠在已有弹窗之上）。`onMount(root)` 里绑事件。
 * 窄屏由 CSS 变成全屏抽屉（见 components.css），不必在这里分支。
 * `wide` 给需要横向空间的表格类弹窗（成绩录入、点名名单）。
 */
export function openModal({ title, body, footer = '', onMount, wide = false }) {
  const root = qs('#modal-root');
  const layer = document.createElement('div');
  layer.className = 'modal-layer';
  layer.innerHTML = `
    <div class="modal-mask" data-mask>
      <div class="modal${wide ? ' wide' : ''}" role="dialog" aria-modal="true">
        <div class="modal-head">
          <h3>${title}</h3>
          <button class="btn btn-sm btn-ghost" type="button" data-close>关闭</button>
        </div>
        <div class="modal-body">${body}</div>
        ${footer ? `<div class="modal-foot">${footer}</div>` : ''}
      </div>
    </div>`;
  root.appendChild(layer);

  const close = () => layer.remove();
  const mask = layer.querySelector('[data-mask]');
  mask.addEventListener('click', (event) => {
    if (event.target === mask) close();
  });
  layer.querySelectorAll('[data-close]').forEach((btn) => btn.addEventListener('click', close));

  if (typeof onMount === 'function') onMount(layer);
  return layer;
}

// Esc 关最上面那层：全局只挂一次，没有弹窗时什么也不做
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && modalOpen()) closeModal();
});

/* ---------- 确认框 ---------- */

export function confirmBox(message, { okText = '确定', danger = false } = {}) {
  return new Promise((resolve) => {
    const done = (value) => {
      closeModal();
      resolve(value);
    };
    openModal({
      title: '请确认',
      body: `<p>${message}</p>`,
      footer: `
        <button class="btn" type="button" data-cancel>取消</button>
        <button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" type="button" data-ok>${okText}</button>`,
      onMount(root) {
        root.querySelector('[data-cancel]').addEventListener('click', () => done(false));
        root.querySelector('[data-ok]').addEventListener('click', () => done(true));
      },
    });
  });
}
