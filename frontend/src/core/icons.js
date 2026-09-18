/**
 * 内联 SVG 图标。
 *
 * 一律内联，不走任何图标 CDN —— 部署环境离线，外部资源会让页面在目标机器上
 * 变慢或直接不显示（旧应用唯一的公网依赖就是个反面教材）。
 * 统一 18×18、`currentColor`，跟随文字颜色。
 */

const PATHS = {
  check: '<path d="M4 10.5l4 4 8-9"/>',
  book: '<path d="M4 5.5A2 2 0 0 1 6 3.5h10v13H6a2 2 0 0 0-2 2z"/><path d="M4 5.5v13"/>',
  message:
    '<path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h9A1.5 1.5 0 0 1 16 5.5v6A1.5 1.5 0 0 1 14.5 13H8l-4 3.5z"/>',
  list: '<path d="M4 6h12M4 10h12M4 14h8"/>',
  pencil:
    '<path d="M7.5 3.5h5v2.5h-5z"/><path d="M7.5 4.5h-2a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-10a1 1 0 0 0-1-1h-2"/><path d="M7.5 9.5h5M7.5 12.5h3.5"/>',
  calendar:
    '<path d="M6.5 4v2.5M13.5 4v2.5"/><path d="M4.5 6h11v9.5h-11z"/><path d="M4.5 9.2h11"/>',
  chart:
    '<path d="M4 4v12h12"/><path d="M7 13V8.5M10.5 13V6M14 13v-3"/>',
  building:
    '<path d="M4.5 16.5V5.5h7v11"/><path d="M11.5 9.5h4v7"/><path d="M6.5 8.5h3M6.5 11.5h3M6.5 14h3M13 12h1M13 14.5h1"/>',
  edit: '<path d="M4 16h4l9-9-4-4-9 9z"/>',
  trash: '<path d="M5 7h10M9 7V5h2v2M7 7l1 10h4l1-10"/>',
  plus: '<path d="M10 4v12M4 10h12"/>',
  import: '<path d="M10 13V4M6 8l4-4 4 4M4 16h12"/>',
  export: '<path d="M10 4v9M6 9l4 4 4-4M4 16h12"/>',
  template: '<path d="M5 3h7l4 4v10H5z"/><path d="M12 3v4h4"/>',
  users: '<path d="M7 8.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z"/><path d="M2.5 16c0-2.5 2-4 4.5-4s4.5 1.5 4.5 4"/><path d="M13.5 7.2a2.2 2.2 0 1 0 0-4.4"/><path d="M14 12.2c2 .2 3.5 1.6 3.5 3.8"/>',
  phone:
    '<path d="M5 3.5h3l1.5 3.5-2 1.5a9 9 0 0 0 4 4l1.5-2 3.5 1.5v3a1.5 1.5 0 0 1-1.7 1.5C9.6 15.9 4.1 10.4 3.5 5.2A1.5 1.5 0 0 1 5 3.5z"/>',
  down: '<path d="M9 6l4 4-4 4"/>',
};

export function icon(name, size = 18) {
  const body = PATHS[name] || PATHS.list;
  return `<svg viewBox="0 0 20 20" width="${size}" height="${size}" fill="none"
    stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"
    aria-hidden="true">${body}</svg>`;
}
