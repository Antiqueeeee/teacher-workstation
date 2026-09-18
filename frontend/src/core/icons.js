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
  edit: '<path d="M4 16h4l9-9-4-4-9 9z"/>',
  trash: '<path d="M5 7h10M9 7V5h2v2M7 7l1 10h4l1-10"/>',
  plus: '<path d="M10 4v12M4 10h12"/>',
  import: '<path d="M10 13V4M6 8l4-4 4 4M4 16h12"/>',
  export: '<path d="M10 4v9M6 9l4 4 4-4M4 16h12"/>',
  template: '<path d="M5 3h7l4 4v10H5z"/><path d="M12 3v4h4"/>',
  down: '<path d="M9 6l4 4-4 4"/>',
};

export function icon(name, size = 18) {
  const body = PATHS[name] || PATHS.list;
  return `<svg viewBox="0 0 20 20" width="${size}" height="${size}" fill="none"
    stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"
    aria-hidden="true">${body}</svg>`;
}
