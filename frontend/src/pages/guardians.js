/**
 * 家长通讯。
 *
 * 表单里填的是**学生姓名**，不是 id —— 老师记的是名字。
 * 后端会在保存前把它解析成 student_id 并带出班级；重名或查无此人时明确报错，
 * 不会静默挂到同名学生身上（见 backend/app/services/guardian_service.py）。
 */

export const guardiansPageDef = { specKey: 'guardians', group: '学生管理', iconName: 'phone' };
