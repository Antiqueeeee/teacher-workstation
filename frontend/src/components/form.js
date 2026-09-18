/**
 * 通用表单：按注册表的 `fields` 声明渲染，不手写字段。
 *
 * 校验以**后端为准**：这里只做「必填为空就别发请求」这种显然的即时反馈，
 * 真正的规则（日期格式、下拉范围、长度）由后端统一执行 ——
 * 前端校验只是体验，不是防线（旧应用的「清空并替换」导入就是绕过了前端校验）。
 */

import { api } from '../core/api.js';
import { esc, qs } from '../core/dom.js';
import { toast, closeModal, openModal } from './ui.js';

function inputHtml(field, value) {
  const id = `f-${field.k}`;
  const common = `id="${id}" name="${esc(field.k)}" class="input"`;
  const current = value === null || value === undefined ? '' : value;

  switch (field.type) {
    case 'number':
      return `<input ${common} type="number" inputmode="numeric" value="${esc(current)}">`;
    case 'date':
      return `<input ${common} type="date" value="${esc(String(current).slice(0, 10))}">`;
    case 'textarea':
      return `<textarea id="${id}" name="${esc(field.k)}" class="textarea" rows="4">${esc(current)}</textarea>`;
    case 'select':
      return `<select id="${id}" name="${esc(field.k)}" class="select">
        <option value="">请选择</option>
        ${field.options
          .map(
            (option) =>
              `<option value="${esc(option)}"${String(current) === String(option) ? ' selected' : ''}>${esc(option)}</option>`,
          )
          .join('')}
      </select>`;
    case 'checkbox':
      return `<div class="checkbox-row">
        <input id="${id}" name="${esc(field.k)}" type="checkbox"${current ? ' checked' : ''}>
        <label for="${id}">${esc(field.label)}</label>
      </div>`;
    default:
      return `<input ${common} type="text" value="${esc(current)}">`;
  }
}

/** 渲染一个字段的外壳（标签 + 控件 + 提示）。勾选框自带标签，不再重复。 */
function fieldHtml(field, value) {
  const control = inputHtml(field, value);
  if (field.type === 'checkbox') {
    return `<div class="field ${field.full ? 'full' : ''}">${control}</div>`;
  }
  return `<div class="field ${field.full ? 'full' : ''}">
    <label for="f-${esc(field.k)}">${esc(field.label)}${field.required ? ' <span class="req">*</span>' : ''}</label>
    ${control}
    ${field.hint ? `<span class="hint">${esc(field.hint)}</span>` : ''}
  </div>`;
}

/** 从表单里读回值（按声明类型转换，具体校验交给后端）。 */
export function readForm(root, spec) {
  const values = {};
  for (const field of spec.fields) {
    if (!field.editable) continue;
    const node = qs(`[name="${field.k}"]`, root);
    if (!node) continue;
    if (field.type === 'checkbox') {
      values[field.k] = node.checked;
    } else {
      const raw = node.value;
      values[field.k] = field.type === 'number' && raw !== '' ? Number(raw) : raw;
    }
  }
  return values;
}

/**
 * 打开新增/编辑表单。返回保存后的记录；用户取消则返回 null。
 */
  /** 字段的初始值：编辑时用记录里的值（空就是空），新增时用预填值或声明里的默认值。
   *
   * `row` 没有 id 时当作**预填**（例如值日看板上点某天新增，房间与星期已经定了）——
   * 判定编辑与否只能看 id，不能只看「有没有传对象」。
   */
  function initialValue(field, row, isEdit) {
    if (isEdit) return row[field.k];
    const given = row ? row[field.k] : undefined;
    return given === undefined || given === null || given === '' ? field.default : given;
  }

export function openForm(spec, row = null) {
  const isEdit = Boolean(row && row.id);
  return new Promise((resolve) => {
    const fields = spec.fields
      .filter((field) => field.editable)
      .map((field) => fieldHtml(field, initialValue(field, row, isEdit)))
      .join('');

    openModal({
      title: `${isEdit ? '编辑' : '新增'}${spec.entity}`,
      body: `<div class="form-grid">${fields}</div>`,
      footer: `
        <button class="btn" type="button" data-cancel>取消</button>
        <button class="btn btn-primary" type="button" data-save>保存</button>`,
      onMount(root) {
        const cancel = () => {
          closeModal();
          resolve(null);
        };
        root.querySelector('[data-cancel]').addEventListener('click', cancel);

        const save = async () => {
          const values = readForm(root, spec);
          const button = root.querySelector('[data-save]');
          button.disabled = true;
          button.textContent = '保存中…';
          try {
            const saved = isEdit
              ? await api.update(spec.key, row.id, values)
              : await api.create(spec.key, values);
            closeModal();
            toast(isEdit ? '已保存' : `已新增${spec.entity}`);
            resolve(saved);
          } catch (error) {
            // 错误留在弹窗里显示，不关窗 —— 否则用户填的内容就丢了
            button.disabled = false;
            button.textContent = '保存';
            toast(error.message, 'err', 6000);
          }
        };
        root.querySelector('[data-save]').addEventListener('click', save);

        // 回车即保存：一天要录几十条记录时，少一次挪鼠标很实在
        root.addEventListener('keydown', (event) => {
          if (event.key === 'Enter' && !event.shiftKey && event.target.tagName !== 'TEXTAREA') {
            event.preventDefault();
            save();
          }
        });

        const first = root.querySelector('.modal-body input, .modal-body textarea, .modal-body select');
        if (first) first.focus();
      },
    });
  });
}
