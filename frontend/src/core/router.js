/**
 * 哈希路由 + 页面注册表。
 *
 * 页面对象：`{ key, title, group, render() → {html, bind?} }`
 *   - `render()` **异步**（旧应用是同步读全局数据，这里要等接口）；
 *   - 与旧应用同一套模型：返回 HTML 字符串 + 可选的 `bind(root)` 绑事件。
 *
 * 两条来自缺陷清单的纪律：
 *   1. 渲染失败要出**错误卡片**并说明原因，不能留一片空白；
 *   2. 先渲染再绑定，绑定失败也要提示，而不是静默变成死页面。
 */

import { errorCard } from './errors.js';

const pages = new Map();
let defaultKey = null;

export function register(page) {
  pages.set(page.key, page);
  if (!defaultKey) defaultKey = page.key;
}

export function registeredPages() {
  return Array.from(pages.values());
}

export function currentKey() {
  return (window.location.hash || '').replace(/^#/, '').trim();
}

export function go(key) {
  if (currentKey() === key) {
    render();
    return;
  }
  window.location.hash = key;
}

function container() {
  return document.getElementById('content');
}

export async function render() {
  const target = container();
  if (!target) return;

  const key = currentKey();
  const page = pages.get(key) || pages.get(defaultKey);
  if (!page) {
    target.innerHTML = '<div class="empty">还没有可用的页面。</div>';
    return;
  }

  target.innerHTML = '<div class="empty">加载中…</div>';
  try {
    const result = await page.render();
    target.innerHTML = result.html ?? '';
    if (typeof result.bind === 'function') {
      try {
        result.bind(target);
      } catch (error) {
        // 绑定失败不掩盖：界面已经出来了，但按钮是死的，必须让用户知道
        console.error('页面事件绑定失败', error);
        target.insertAdjacentHTML('afterbegin', errorCard(error));
      }
    }
    document.title = `${page.title} · 班主任工作台`;
  } catch (error) {
    console.error('页面渲染失败', error);
    target.innerHTML = errorCard(error);
    target.querySelector('[data-action="retry"]')?.addEventListener('click', () => render());
    document.title = '出错了 · 班主任工作台';
  }
}

export function start() {
  window.addEventListener('hashchange', render);
  return render();
}

export function setDefault(key) {
  defaultKey = key;
}
