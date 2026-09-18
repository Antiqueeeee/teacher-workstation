/**
 * 学生档案。
 *
 * 与别的页面**没有任何区别** —— 因为学生档案的表声明也会出现在 `/meta/registry` 里
 * （后端把它当「动态表」注册，声明按库里的字段定义现算）。
 * 所以字段管理里加一个字段，刷新页面这个列表和表单就多一列。
 */

export const studentsPageDef = { specKey: 'students', group: '学生管理', iconName: 'users' };
