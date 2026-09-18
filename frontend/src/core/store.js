/**
 * 前端内存态。
 *
 * 只放**界面状态** —— 注册表缓存、当前班级、每个列表页的查询条件。
 * 这些既不该进数据库，也不该每次都发请求（见 CONTRIBUTING §2 的分工原则）。
 */

export const store = {
  /** 表注册表：key → spec（启动时拉一次，之后同步取用） */
  registry: new Map(),
  /** 注册表顺序（导航按它排） */
  specOrder: [],
  /** 当前班级 id；单班级场景为 null，不必让用户感知「班级」这个概念 */
  currentClassId: null,
  /** 每个列表页的查询状态：key → {q, filters, sort, dir, page, pageSize} */
  listState: new Map(),
};

export function setRegistry(specs) {
  store.registry.clear();
  store.specOrder = [];
  for (const spec of specs) {
    store.registry.set(spec.key, spec);
    store.specOrder.push(spec.key);
  }
}

export function getSpec(key) {
  return store.registry.get(key) || null;
}

/** 取（必要时初始化）某个列表页的查询状态。 */
export function getListState(spec) {
  if (!store.listState.has(spec.key)) {
    store.listState.set(spec.key, {
      q: '',
      filters: {},
      sort: spec.defaultSort?.k || 'id',
      dir: spec.defaultSort?.dir < 0 ? 'desc' : 'asc',
      page: 1,
      pageSize: 20,
    });
  }
  return store.listState.get(spec.key);
}

export function resetListState(spec) {
  store.listState.delete(spec.key);
}

/** 把查询状态转成接口参数（空值会被 api 层丢掉）。 */
export function toParams(state) {
  const params = {
    q: state.q,
    sort: state.sort,
    dir: state.dir,
    page: state.page,
    pageSize: state.pageSize,
  };
  if (store.currentClassId) params.classId = store.currentClassId;
  for (const [key, value] of Object.entries(state.filters || {})) {
    params[`filter.${key}`] = value;
  }
  return params;
}
