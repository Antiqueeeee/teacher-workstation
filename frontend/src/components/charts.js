/**
 * 极简图表：折线、柱状、横条。**手写 SVG，不引任何图表库**。
 *
 * 为什么不用现成的：整个前端没有构建步骤、也不用 CDN（部署环境不联网），
 * 引一个图表库就得维护打包流程或把几百 KB 塞进仓库。这里要的只是「一条趋势线 + 几根柱子」，
 * 手写反而更可控（旧应用也是手写的，这条路径已经验证过）。
 *
 * 三处刻意的做法：
 * - **空值不画成 0**：出勤率里没登记的日子是 `null`，折线在那里**断开** ——
 *   连上去就等于说「那天满勤」（旧应用就是这么把未登记画成 100% 的）；
 * - 纵轴范围按数据自适应，不再写死 `min:60, max:100`；
 * - 每张图都给 `title`/`aria-label`，鼠标停在点上能看到具体数值。
 */

import { esc } from '../core/dom.js';

const PALETTE = ['#2a93b8', '#3fc7a3', '#f0be3c', '#8b7be8', '#ff9a3c', '#e84c4c'];

function scale(values, { pad = 0.1 } = {}) {
  const numbers = values.filter((value) => typeof value === 'number' && !Number.isNaN(value));
  if (!numbers.length) return { min: 0, max: 1 };
  let min = Math.min(...numbers);
  let max = Math.max(...numbers);
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const span = max - min;
  return { min: min - span * pad, max: max + span * pad };
}

/** 折线图。`points` 是 `[{label, value}]`，`value` 为 null 表示**那天没有数据**。 */
export function lineChart(points, { width = 640, height = 160, suffix = '', min, max } = {}) {
  if (!points.length) return '<div class="muted">没有数据</div>';
  const padding = { top: 12, right: 8, bottom: 20, left: 34 };
  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;
  const values = points.map((point) => point.value);
  const bounds = scale(values);
  const low = min !== undefined ? min : bounds.min;
  const high = max !== undefined ? max : bounds.max;
  const x = (index) =>
    padding.left + (points.length === 1 ? innerW / 2 : (innerW * index) / (points.length - 1));
  const y = (value) => padding.top + innerH - ((value - low) / (high - low || 1)) * innerH;

  // 空值把折线切断：分段画，连上去就等于说「那天有数据」
  const segments = [];
  let current = [];
  points.forEach((point, index) => {
    if (typeof point.value === 'number') {
      current.push([x(index), y(point.value), point, index]);
    } else if (current.length) {
      segments.push(current);
      current = [];
    }
  });
  if (current.length) segments.push(current);

  const gridLines = [0, 0.5, 1]
    .map((ratio) => {
      const value = low + (high - low) * ratio;
      const yy = y(value);
      return `<line x1="${padding.left}" y1="${yy}" x2="${width - padding.right}" y2="${yy}"
        class="chart-grid"/><text x="4" y="${yy + 4}" class="chart-axis">${Math.round(value)}${suffix}</text>`;
    })
    .join('');

  const lines = segments
    .map(
      (segment) =>
        `<polyline class="chart-line" points="${segment.map(([xx, yy]) => `${xx},${yy}`).join(' ')}"/>`,
    )
    .join('');
  const dots = segments
    .flat()
    .map(
      ([xx, yy, point]) =>
        `<circle class="chart-dot" cx="${xx}" cy="${yy}" r="2.5"><title>${esc(point.label)}：${
          typeof point.value === 'number' ? `${point.value}${suffix}` : '没有数据'
        }</title></circle>`,
    )
    .join('');

  const labels = points
    .map((point, index) =>
      index % Math.ceil(points.length / 7) === 0
        ? `<text x="${x(index)}" y="${height - 6}" class="chart-axis mid">${esc(point.label)}</text>`
        : '',
    )
    .join('');

  return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img"
    aria-label="趋势图，共 ${points.length} 个点">
    ${gridLines}${lines}${dots}${labels}
  </svg>`;
}

/** 柱状图（分组）。`items` 是 `[{label, value, color?}]`。 */
export function barChart(items, { height = 150, suffix = '' } = {}) {
  if (!items.length) return '<div class="muted">没有数据</div>';
  const max = Math.max(...items.map((item) => item.value || 0), 1);
  return `<div class="bar-chart" style="height:${height}px">${items
    .map(
      (item) => `<div class="bar-item">
        <div class="bar-value">${item.value || 0}${suffix}</div>
        <div class="bar-track"><div class="bar-fill" style="height:${Math.max(
          2,
          ((item.value || 0) / max) * 100,
        )}%;background:${item.color || PALETTE[0]}"></div></div>
        <div class="bar-label">${esc(item.label)}</div>
      </div>`,
    )
    .join('')}</div>`;
}

/** 横向条：适合「Top N」这种长短差异很大的数。 */
export function hBarList(items, { suffix = '' } = {}) {
  if (!items.length) return '<div class="muted">没有数据</div>';
  const max = Math.max(...items.map((item) => item.value || 0), 1);
  return `<div class="hbar-list">${items
    .map(
      (item, index) => `<div class="hbar-row">
        <span class="hbar-label" title="${esc(item.label)}">${esc(item.label)}</span>
        <span class="hbar-track"><span class="hbar-fill" style="width:${((item.value || 0) / max) * 100}%;
          background:${PALETTE[index % PALETTE.length]}"></span></span>
        <span class="hbar-value">${item.value || 0}${suffix}</span>
      </div>`,
    )
    .join('')}</div>`;
}

/** 双线折线（沟通与大事记这种同月对比）。 */
export function multiLineChart(series, labels, { width = 640, height = 170 } = {}) {
  const all = series.flatMap((item) => item.values);
  const bounds = scale(all, { pad: 0 });
  const padding = { top: 12, right: 8, bottom: 20, left: 30 };
  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;
  const x = (index) =>
    padding.left + (labels.length === 1 ? innerW / 2 : (innerW * index) / (labels.length - 1));
  const y = (value) =>
    padding.top + innerH - ((value - bounds.min) / (bounds.max - bounds.min || 1)) * innerH;

  return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="多条趋势">
    ${series
      .map(
        (item, index) => `<polyline class="chart-line" style="stroke:${PALETTE[index % PALETTE.length]}"
          points="${item.values.map((value, i) => `${x(i)},${y(value)}`).join(' ')}"/>`,
      )
      .join('')}
    ${labels
      .map((label, index) =>
        index % Math.ceil(labels.length / 6) === 0
          ? `<text x="${x(index)}" y="${height - 6}" class="chart-axis mid">${esc(label)}</text>`
          : '',
      )
      .join('')}
  </svg>
  <div class="chart-legend">${series
    .map(
      (item, index) =>
        `<span><i style="background:${PALETTE[index % PALETTE.length]}"></i>${esc(item.label)}</span>`,
    )
    .join('')}</div>`;
}
