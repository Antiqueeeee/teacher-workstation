/**
 * 家长联系日志（沟通留档）。
 *
 * 用户提的第三个痛点落在这里：「和家长沟通之后留档」。页面本身是通用链路
 * （列表/表单/导入导出），**独有的那一块是每行后面的「附件」** ——
 * 照片与录音都在那里上传、回看、播放（见 components/media-picker.js）。
 *
 * 音频是老师自己用手机录完再上传的：本项目不触发录制、不要麦克风权限。
 */

export const contactsPageDef = { specKey: 'contacts', group: '家校沟通', iconName: 'phone' };
