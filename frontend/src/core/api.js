/**
 * 后端接口封装。
 *
 * 后端一律返回 `{ok:true, data, meta}` 或 `{ok:false, error:{code,message,detail}}`，
 * 这里统一拆包、统一抛 `ApiError` —— 页面里就不会出现「到处判断 res.ok」，
 * 也不会出现「某个页面忘了处理失败」这种半成品状态。
 */

import { describeError } from './errors.js';

const BASE = '/api/v1';

export class ApiError extends Error {
  constructor(code, message, detail) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.detail = detail;
  }
}

/** 把后端响应拆包；失败就抛 ApiError。 */
async function unwrap(response) {
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    // 非 JSON 响应（例如请求打到了静态文件托管）
    throw new ApiError(`HTTP_${response.status}`, '', null);
  }
  if (!payload || payload.ok !== true) {
    const error = payload?.error || { code: `HTTP_${response.status}`, message: '', detail: null };
    throw new ApiError(error.code, error.message || describeError(error), error.detail);
  }
  return payload;
}

function buildUrl(path, params) {
  const url = new URL(BASE + path, window.location.origin);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, value);
    }
  }
  return url;
}

async function request(path, { method = 'GET', body, params } = {}) {
  let response;
  try {
    response = await fetch(buildUrl(path, params), {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (cause) {
    // 网络层失败（服务没起、断网）也要给出可执行的提示
    throw new ApiError('NETWORK', describeError({ code: 'NETWORK' }), cause);
  }
  return unwrap(response);
}

export const api = {
  registry: () => request('/meta/registry').then((p) => p.data),
  health: () => request('/health').then((p) => p.data),

  list: (table, params) => request(`/${table}`, { params }).then((p) => ({ rows: p.data, meta: p.meta })),
  stats: (table, params) => request(`/${table}/stats`, { params }).then((p) => p.data),
  get: (table, id) => request(`/${table}/${id}`).then((p) => p.data),
  create: (table, values, params) =>
    request(`/${table}`, { method: 'POST', body: values, params }).then((p) => p.data),
  update: (table, id, values) => request(`/${table}/${id}`, { method: 'PATCH', body: values }).then((p) => p.data),
  remove: (table, id) => request(`/${table}/${id}`, { method: 'DELETE' }).then((p) => p.data),
  batch: (table, payload) => request(`/${table}/batch`, { method: 'POST', body: payload }).then((p) => p.data),

  /** 上传文件做导入预览（multipart，不能用 JSON 那条路径）。 */
  async importPreview(table, file) {
    const form = new FormData();
    form.append('file', file);
    let response;
    try {
      response = await fetch(buildUrl('/transfer/import', { table }), { method: 'POST', body: form });
    } catch (cause) {
      throw new ApiError('NETWORK', describeError({ code: 'NETWORK' }), cause);
    }
    return unwrap(response).then((p) => p.data);
  },

  importCommit: (table, rows, params) =>
    request('/transfer/import/commit', { method: 'POST', body: { rows }, params }).then((p) => p.data),

  /** 导出/模板直接用链接下载 —— 让浏览器处理文件名与保存对话框，比 fetch 再造 Blob 稳。 */
  exportUrl: (table, params) => buildUrl(`/transfer/export/${table}.xlsx`, params).toString(),
  templateUrl: (table) => buildUrl(`/transfer/template/${table}.xlsx`).toString(),
};

/** 触发浏览器下载（同源 GET，直接给 <a download> 点一下）。 */
export function triggerDownload(url) {
  const link = document.createElement('a');
  link.href = url;
  link.rel = 'noopener';
  document.body.appendChild(link);
  link.click();
  link.remove();
}
