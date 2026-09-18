/**
 * 应用入口：拉注册表 → 构建页面 → 建导航 → 启动路由。
 *
 * 顺序很关键：注册表**必须先拉回来**，页面标题/列/字段全部来自后端的表声明。
 * 前端不再抄一份字段定义 —— 两边各描述一遍同一件事，迟早不一致
 * （旧应用 40 条缺陷里有相当一部分就是这个形状）。
 */

import { createCrudPage } from './components/crud-page.js';
import { api } from './core/api.js';
import { esc, qs } from './core/dom.js';
import { errorCard } from './core/errors.js';
import { icon } from './core/icons.js';
import { currentKey, register, setDefault, start } from './core/router.js';
import { getSpec, setRegistry } from './core/store.js';
import { attendancePageDef } from './pages/attendance.js';
import { dormDutyPageDef } from './pages/dorm-duty.js';
import { contactsPageDef } from './pages/contacts.js';
import { countdownsPageDef } from './pages/countdowns.js';
import { homePage } from './pages/home.js';
import { cadresPageDef } from './pages/cadres.js';
import { activitiesPageDef } from './pages/class_activities.js';
import { eventsPageDef } from './pages/class_events.js';
import { conflictsPageDef } from './pages/conflicts.js';
import { courseClassesPageDef } from './pages/course_classes.js';
import { courseScoresPageDef } from './pages/course_scores.js';
import { courseStudentsPageDef } from './pages/course_students.js';
import { coursesPageDef } from './pages/courses.js';
import { dormsPageDef } from './pages/dorms.js';
import { feeLedgerPageDef } from './pages/fee_ledger.js';
import { feeRecordsPageDef } from './pages/fee_records.js';
import { feesPageDef } from './pages/fees.js';
import { dutyGroupsPageDef } from './pages/duty_groups.js';
import { grantsPageDef } from './pages/grants.js';
import { guardiansPageDef } from './pages/guardians.js';
import { meetingsPageDef } from './pages/meetings.js';
import { healthRecordsPageDef } from './pages/health_records.js';
import { homeworkPageDef } from './pages/homework.js';
import { rulesPageDef } from './pages/rules.js';
import { dashboardPage } from './pages/dashboard.js';
import { disciplinesPageDef } from './pages/disciplines.js';
import { talksPageDef } from './pages/talks.js';
import { visitsPageDef } from './pages/visits.js';
import { schedulePageDef } from './pages/schedule.js';
import { scoresPageDef } from './pages/scores.js';
import { seatsPageDef } from './pages/seats.js';
import { settingsPage } from './pages/settings.js';
import { studentsPageDef } from './pages/students.js';
import { substitutePage } from './pages/substitute.js';
import { youthMembersPageDef } from './pages/youth_members.js';
import { templatesPageDef } from './pages/templates.js';
import { todosPageDef } from './pages/todos.js';

// 顺序即侧栏顺序；分组由页面自己声明
const PAGE_DEFS = [
  homePage,
  substitutePage,
  dashboardPage,
  studentsPageDef,
  guardiansPageDef,
  disciplinesPageDef,
  healthRecordsPageDef,
  grantsPageDef,
  contactsPageDef,
  visitsPageDef,
  talksPageDef,
  meetingsPageDef,
  conflictsPageDef,
  activitiesPageDef,
  eventsPageDef,
  cadresPageDef,
  youthMembersPageDef,
  dutyGroupsPageDef,
  feesPageDef,
  feeRecordsPageDef,
  feeLedgerPageDef,
  attendancePageDef,
  homeworkPageDef,
  schedulePageDef,
  scoresPageDef,
  coursesPageDef,
  courseClassesPageDef,
  courseStudentsPageDef,
  courseScoresPageDef,
  dormsPageDef,
  dormDutyPageDef,
  seatsPageDef,
  countdownsPageDef,
  todosPageDef,
  rulesPageDef,
  templatesPageDef,
  settingsPage,
];

/** 数据就绪后才构建页面对象（见各 pages/*.js 顶部说明）。 */
let pages = [];

function currentPage() {
  // 复用 router 的 hash 解析，避免同一逻辑两份实现
  const key = currentKey();
  return pages.find((page) => page.key === key) || pages[0];
}

function buildNav() {
  const nav = qs('#nav');
  const groups = new Map();
  for (const page of pages) {
    if (!groups.has(page.group)) groups.set(page.group, []);
    groups.get(page.group).push(page);
  }
  nav.innerHTML = Array.from(groups.entries())
    .map(
      ([group, groupPages]) => `
      <div class="nav-group">
        <div class="nav-group-title">${esc(group)}</div>
        ${groupPages
          .map(
            (page) => `<button class="nav-item" type="button" data-nav="${esc(page.key)}">
              ${icon(page.icon)}<span>${esc(page.title)}</span>
            </button>`,
          )
          .join('')}
      </div>`,
    )
    .join('');

  nav.addEventListener('click', (event) => {
    const button = event.target.closest('[data-nav]');
    if (!button) return;
    closeDrawer();
    window.location.hash = button.dataset.nav;
  });
}

function syncChrome() {
  const page = currentPage();
  if (!page) return;
  qs('#page-title').textContent = page.title;
  document.querySelectorAll('[data-nav]').forEach((button) => {
    button.classList.toggle('active', button.dataset.nav === page.key);
  });
}

/* ---------- 窄屏抽屉 ---------- */

function openDrawer() {
  qs('#sidebar').classList.add('open');
  qs('#scrim').hidden = false;
}

function closeDrawer() {
  qs('#sidebar').classList.remove('open');
  qs('#scrim').hidden = true;
}

function bindShell() {
  qs('#menu-btn').addEventListener('click', openDrawer);
  qs('#scrim').addEventListener('click', closeDrawer);
  window.addEventListener('hashchange', syncChrome);
}

async function bootstrap() {
  try {
    setRegistry(await api.registry());
  } catch (error) {
    // 连注册表都拿不到，多半是服务没起或网络不通 —— 直接把原因摆在页面上
    qs('#content').innerHTML = errorCard(error);
    return;
  }

  // 两种页面：通用列表页（注册表驱动）与**自定义页面**（首页/看板这类聚合页，
  // 自己实现 render）。判断依据是「有没有自带 render」。
  pages = PAGE_DEFS.map((def) =>
    def.render ? def : createCrudPage({ ...def, spec: getSpec(def.specKey) }),
  );
  pages.forEach(register);
  setDefault(pages[0].key);

  bindShell();
  buildNav();
  syncChrome();

  try {
    const health = await api.health();
    qs('#side-hint').textContent = `v${health.version} · 共 ${health.tables} 个模块`;
  } catch {
    /* 健康检查失败不影响使用：注册表已经拿到了 */
  }

  await start();
}

bootstrap();
