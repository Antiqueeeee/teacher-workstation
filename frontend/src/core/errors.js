/**
 * 错误文案。
 *
 * 目标（来自缺陷清单）：**不再出现「出错了：Cannot read properties of undefined」**。
 * 后端会给出 code + 一句中文 message，这里只兜底「后端没机会说话」的情况
 * （网络断了、服务没起、静态 404 之类），并且一律给出下一步该怎么办。
 */

export const FRIENDLY = {
  NETWORK: '连不上服务。请确认服务还在运行，手机与电脑在同一局域网。',
  TABLE_NOT_FOUND: '这个表不存在，可能是页面缓存过期了，刷新一下试试。',
  NOT_FOUND: '这条记录不存在，可能已被删除。',
  CLASS_ID_REQUIRED: '存在多个班级，请先在顶部选择班级。',
  EXPORT_TOO_LARGE: '命中的记录太多，请先用筛选缩小范围再导出。',
  NO_HEADER_MATCHED: '表头一个字段都没认出来。请先下载导入模板对照列名，或确认没有选错表。',
  EMPTY_FILE: '文件是空的，没有读到内容。',
  NO_DATA_ROWS: '只读到表头，没有数据行。',
  ROW_VALIDATION_FAILED: '有行没通过校验，整批都没有写入。修好后重新提交即可。',
};

/** 把错误对象转成用户能看懂的一句话。 */
export function describeError(error) {
  if (!error) return '发生了未知问题。';
  const { code, message } = error;
  if (message) return message; // 后端给的中文说明通常比本地兜底更具体
  if (code && FRIENDLY[code]) return FRIENDLY[code];
  if (code && code.startsWith('HTTP_')) return `服务返回了 ${code.slice(5)}，请稍后再试。`;
  return '发生了未知问题，请刷新页面重试。';
}

/**
 * 渲染一张错误卡片。
 * 页面渲染失败时给一张卡片，而不是留一片空白 —— 空白没法排查，也没法反馈。
 */
export function errorCard(error) {
  const title = error?.code ? `出错了（${error.code}）` : '出错了';
  const detail = error?.detail ? `<pre class="error-detail">${JSON.stringify(error.detail, null, 2)}</pre>` : '';
  return `
    <div class="card error-card">
      <h3>${title}</h3>
      <p>${describeError(error)}</p>
      ${detail}
      <button class="btn" data-action="retry">重试</button>
    </div>`;
}
