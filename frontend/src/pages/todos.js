/**
 * 待办任务（试点页）。
 *
 * 这里只声明「我是哪张表、放在哪个分组」—— 列、字段、筛选项、搜索范围
 * 全部来自后端注册表（docs/改造方案/03 §5.1），所以加一张表不需要写页面代码。
 *
 * 注意：**不在这里创建页面对象**。页面模块是在启动最开始被 import 的，
 * 那时注册表还没拉回来；`createCrudPage` 由 main.js 在数据就绪后统一调用。
 */

export const todosPageDef = { specKey: 'todos', group: '班级事务', iconName: 'check' };
