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
  /** 恢复软删除的记录 —— 删除确认框里承诺过「可以找回」，就得真有入口。 */
  restore: (table, id) => request(`/${table}/${id}/restore`, { method: 'POST' }).then((p) => p.data),
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

  /** 出勤：按天点名（整体提交）与区间小结。
   *  出勤率一律由后端算 —— 界面这层只显示，不自己数记录条数（旧应用就是那么漂掉的）。 */
  attendanceDay: (date, classId) =>
    request('/attendance/day', { params: { date, classId } }).then((p) => p.data),
  saveAttendanceDay: (payload) =>
    request('/attendance/day', { method: 'PUT', body: payload }).then((p) => p.data),
  attendanceSummary: (from, to, classId) =>
    request('/attendance/summary', { params: { from, to, classId } }).then((p) => p.data),

  /** 宿舍：看板视图（房间 + 床位占用 + 未分配住宿生）。
   *  容量、床位占用都由后端算好，界面不自己数 —— 旧应用就是靠界面按 capacity 现算，
   *  容量读错一次整间房就都错了。 */
  dormTree: (classId) => request('/dorms/tree', { params: { classId } }).then((p) => p.data),
  /** 值日看板：按房间 × 星期分组，分组在后端做（前端分组遇到分页会缺一块）。 */
  dutyBoard: (classId) => request('/dorms/duties', { params: { classId } }).then((p) => p.data),

  /** 座位：看板与四个批量操作。
   *  随机/轮换/交换/回退都在服务端一次事务完成，并返回新的看板 —— 界面不自己算位置。
   *  classId 由调用方传（单班场景可以为空，接口自己取那唯一的班级）。 */
  seatBoard: (classId) => request('/seats/board', { params: { classId } }).then((p) => p.data),
  seatPlan: (payload, classId) =>
    request('/seats/plan', { method: 'PUT', body: payload, params: { classId } }).then((p) => p.data),
  seatRandomize: (classId) =>
    request('/seats/randomize', { method: 'POST', body: {}, params: { classId } }).then((p) => p.data),
  seatShift: (direction, step, classId) =>
    request('/seats/shift', {
      method: 'POST',
      body: { direction, step },
      params: { classId },
    }).then((p) => p.data),
  seatSwap: (payload, classId) =>
    request('/seats/swap', { method: 'POST', body: payload, params: { classId } }).then((p) => p.data),
  seatRestore: (classId) =>
    request('/seats/restore', { method: 'POST', body: {}, params: { classId } }).then((p) => p.data),
  seatClear: (classId) =>
    request('/seats/clear', { method: 'POST', body: {}, params: { classId } }).then((p) => p.data),

  /** 首页与看板聚合：**口径在后端**，前端只显示（首页的数必须与各页一致）。 */
  overview: (classId) => request('/analytics/overview', { params: { classId } }).then((p) => p.data),
  followups: (classId, limit) =>
    request('/analytics/followups', { params: { classId, limit } }).then((p) => p.data),

  /** 媒体：上传（multipart）、一条记录的附件列表、删除。 */
  async mediaUpload(ownerTable, ownerId, file) {
    const form = new FormData();
    form.append("file", file);
    form.append("ownerTable", ownerTable);
    form.append("ownerId", String(ownerId));
    let response;
    try {
      response = await fetch(buildUrl("/media"), { method: "POST", body: form });
    } catch (cause) {
      throw new ApiError("NETWORK", describeError({ code: "NETWORK" }), cause);
    }
    return unwrap(response).then((p) => p.data);
  },
  mediaList: (ownerTable, ownerId) =>
    request("/media", { params: { ownerTable, ownerId } }).then((p) => p.data),
  mediaDelete: (id) => request(`/media/${id}`, { method: "DELETE" }).then((p) => p.data),
  mediaStorage: () => request("/media/storage").then((p) => p.data),
  /** 按日期（可选按学生）真正清理媒体文件 —— 不进回收站，界面要二次确认。 */
  mediaPurge: (payload) => request("/media/purge", { method: "POST", body: payload }).then((p) => p.data),

  /** 设置：班级信息、存储占用与分表行数、清空数据。 */
  settings: (classId) => request('/settings', { params: { classId } }).then((p) => p.data),
  saveClassInfo: (payload, classId) =>
    request('/settings/class', { method: 'PUT', body: payload, params: { classId } }).then((p) => p.data),
  clearData: (payload, classId) =>
    request('/settings/clear', { method: 'POST', body: payload, params: { classId } }).then((p) => p.data),

  /** 时间轴：几类留档按日期合成的一条线（后端合，加一类只改一处）。 */
  timeline: (classId, limit) => request('/analytics/timeline', { params: { classId, limit } }).then((p) => p.data),

  /** 数据看板：出勤趋势、违纪分布、Top 榜、月度走势。 */
  dashboard: (days, classId) => request('/analytics/dashboard', { params: { days, classId } }).then((p) => p.data),

  /** 代课/交接简报（某一天；后端汇总，用的还是各模块自己的口径）。 */
  substituteBrief: (date, classId) =>
    request('/analytics/substitute', { params: { date, classId } }).then((p) => p.data),

  /** 班级费用：概览与某个项目的明细（状态是推导值，只在后端算）。 */
  feeOverview: (classId) => request('/fees/overview', { params: { classId } }).then((p) => p.data),  feeCategory: (categoryId) => request(`/fees/categories/${categoryId}`).then((p) => p.data),
  feeSetAmount: (categoryId, amountCents, backfill) =>
    request(`/fees/categories/${categoryId}/amount`, {
      method: 'PUT',
      body: { amountCents, backfill },
    }).then((p) => p.data),

  /** 学科与成绩：课程看板 / 课程详情 / 成绩分析 / 批量加名单。
   *  得分率、及格、名次全部由后端算（按满分算，不写死 60 分）—— 界面只显示。 */
  courseOverview: () => request('/courses/overview').then((p) => p.data),
  courseDetail: (courseId) => request(`/courses/${courseId}/detail`).then((p) => p.data),
  courseAnalysis: (courseId, classId) =>
    request(`/courses/${courseId}/analysis`, { params: { classId } }).then((p) => p.data),
  courseAddStudents: (courseId, courseClassId, names) =>
    request(`/courses/${courseId}/students`, {
      method: 'POST',
      body: { courseClassId, names },
    }).then((p) => p.data),

  /** 学生一生一档：后端聚合的全部痕迹（各段的数都从所属模块的口径服务取）。 */
  studentArchive: (studentId) => request(`/students/${studentId}/archive`).then((p) => p.data),

  /** 评语草稿：结构化维度 + 可编辑文本（末尾固定「请人工复核」）。 */
  commentDraft: (studentId) => request(`/students/${studentId}/comment-draft`).then((p) => p.data),

  /** 学生档案：同名/同学号冲突报告（学生档案页面顶部据此提示）。 */
  studentConflicts: (classId) =>
    request('/students/name-conflicts', { params: { classId } }).then((p) => p.data),

  /** 成绩：录入表与报表。
   *  名次、及格率、得分率全部由后端算 —— 界面这层不自己数、也不自己排。 */
  scoreSheet: (examId) => request(`/exams/${examId}/sheet`).then((p) => p.data),
  saveScoreSheet: (examId, cells) =>
    request(`/exams/${examId}/sheet`, { method: 'PUT', body: { cells } }).then((p) => p.data),
  scoreReport: (examId) => request(`/exams/${examId}/report`).then((p) => p.data),
  saveExamSubjects: (examId, subjects) =>
    request(`/exams/${examId}/subjects`, { method: 'PUT', body: { subjects } }).then((p) => p.data),
  clearExamScores: (examId) =>
    request(`/exams/${examId}/clear-scores`, { method: 'POST' }).then((p) => p.data),
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
