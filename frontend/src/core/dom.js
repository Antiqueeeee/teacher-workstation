/**
 * 极简 DOM 工具。
 *
 * 不引框架、不引构建 —— 页面仍然沿用旧应用那套「拼 HTML 字符串 + 绑事件」的写法
 * （见 CONTRIBUTING §6），只是把取数改成异步。33 个页面全重写一遍的代价换不来收益。
 */

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

/** HTML 转义。任何插进模板里的数据都要过它 —— 一个带 < 的备注就能把页面结构搞坏。 */
export function esc(value) {
  if (value === null || value === undefined) return '';
  return String(value).replace(/[&<>"']/g, (ch) => ESCAPES[ch]);
}

export function qs(selector, root = document) {
  return root.querySelector(selector);
}

export function qsa(selector, root = document) {
  return Array.from(root.querySelectorAll(selector));
}

export function on(root, eventName, handler, options) {
  root.addEventListener(eventName, handler, options);
}

/**
 * 事件委托：给容器绑一次，按选择器分发。
 * 列表里几百行的「编辑 / 删除」按钮因此只用一个监听器，重渲染也不必重新绑定。
 */
export function delegate(root, eventName, selector, handler) {
  root.addEventListener(eventName, (event) => {
    const target = event.target.closest(selector);
    if (target && root.contains(target)) handler(event, target);
  });
}

/** 把 dataset 里的字段取出来（`data-x="1"` → `{x: '1'}` 中取 x）。 */
export function data(node, key) {
  return node.dataset ? node.dataset[key] : undefined;
}

/** 生成一个唯一的 DOM id（表单 label/for 用）。 */
let idSeed = 0;
export function uid(prefix = 'el') {
  idSeed += 1;
  return `${prefix}-${idSeed}`;
}
