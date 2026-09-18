/**
 * 展示层格式化。
 *
 * 同一份数据在列表、详情、导出里必须长得一样，所以格式化只在这里写一次。
 */

export const DASH = '—';

/** 空值统一显示破折号，而不是「undefined」或空白 —— 空白的行看起来像加载失败。 */
export function text(value) {
  if (value === null || value === undefined || value === '') return DASH;
  return String(value);
}

/** 日期：后端给 ISO（2026-09-01），这里只截日期部分。 */
export function dateText(value) {
  if (!value) return DASH;
  return String(value).slice(0, 10);
}

export function boolText(value) {
  return value ? '是' : '否';
}

export function numberText(value) {
  if (value === null || value === undefined || value === '') return DASH;
  return String(value);
}

/** 布尔值渲染成小徽标，列表里比「是/否」两个汉字更好扫。 */
export function boolBadge(value, onText = '是', offText = '否') {
  return value
    ? `<span class="badge badge-mint">${onText}</span>`
    : `<span class="badge badge-ink">${offText}</span>`;
}

/** 按 spec 里声明的类型渲染一个单元格。 */
export function cellValue(field, value) {
  if (!field) return text(value);
  switch (field.type) {
    case 'checkbox':
      return boolText(value);
    case 'date':
      return dateText(value);
    case 'number':
      return numberText(value);
    default:
      return text(value);
  }
}
