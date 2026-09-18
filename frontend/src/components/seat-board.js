/**
 * 座位表看板：讲台 + 网格，点选交换、点空格子放人。
 *
 * 交互刻意做成**点选**而不是拖拽：手机上没有拖拽，而班主任用手机的时间不比电脑少。
 * 点一个座位选中它，再点另一个座位就交换（目标空着就是挪过去）；左边的「未排座」
 * 列表里点一个学生，再点一个空格子就把他放进去。
 *
 * 三处与旧应用不同：
 * - 备注**看得见**（格子上带小点，鼠标悬浮显示全文；旧应用只在 title 属性里，
 *   连打印都印不出来）；
 * - 锁定标识看得见，锁定的座位不参与随机与轮换；
 * - 随机/轮换/清空之后都有一次**回退**（旧应用直接整体替换 `DB.data.seats`，做错了没退路）。
 *
 * 选中状态存在 JS 里（`picked`），不在 DOM 里：重绘网格不会丢掉选中，
 * 也不需要为「点一下」去请求一次服务器。
 */

import { api } from '../core/api.js';
import { esc } from '../core/dom.js';
import { getSpec, store } from '../core/store.js';
import { openForm } from './form.js';
import { closeModal, confirmBox, openModal, toast } from './ui.js';

const DIRECTIONS = [
  ['up', '整体前移一排'],
  ['down', '整体后移一排'],
  ['left', '整体左移一列'],
  ['right', '整体右移一列'],
];

let picked = null; // {kind:'seat', seatId, name, locked} | {kind:'student', studentId, name}
let lastBoard = null;

/* ---------------------------------------------------------------- 渲染 */

function cellHtml(cell) {
  const classes = ['seat-cell', cell.studentName ? 'taken' : 'empty'];
  if (cell.locked) classes.push('locked');
  if (cell.orphan) classes.push('orphan');
  if (picked?.kind === 'seat' && picked.seatId === cell.seatId) classes.push('picked');

  // 备注与锁定用小标记显示：备注是被随机排位专门保护下来的信息，不能只藏在 title 里
  const marks = `${cell.locked ? '🔒' : ''}${cell.note ? '·' : ''}`;
  return `<button class="${classes.join(' ')}" type="button"
    ${cell.seatId ? `data-seat="${cell.seatId}"` : ''}
    data-row="${cell.row}" data-col="${cell.col}"
    title="${esc(cell.note || (cell.studentName ? '' : '空座位 —— 点左边的学生再点这里'))}">
    <span class="seat-name">${esc(cell.studentName || '空')}</span>
    ${marks ? `<span class="seat-mark">${esc(marks)}</span>` : ''}
  </button>`;
}

function hintHtml() {
  if (!picked) {
    return '点一个座位选中它，再点另一个座位就交换；点左边的学生再点空格子就把他放进去。';
  }
  if (picked.kind === 'student') {
    return `已选中学生 <strong>${esc(picked.name)}</strong> —— 点一个<strong>空座位</strong>把他放进去。`;
  }
  return `<span>已选中 <strong>${esc(picked.name || '空座位')}</strong> —— 点另一个格子交换/挪动。</span>
    <button class="btn btn-sm" type="button" data-act="lock">${picked.locked ? '解锁' : '锁定'}</button>
    <button class="btn btn-sm" type="button" data-act="edit">改备注 / 换人</button>
    <button class="btn btn-sm btn-ghost" type="button" data-act="free">腾空</button>
    <button class="btn btn-sm btn-ghost" type="button" data-act="cancel">取消选中</button>`;
}

export function boardHtml(board) {
  const head = `<tr><th class="seat-row-head"></th>${Array.from(
    { length: board.cols },
    (_, index) => `<th class="seat-col-head">第 ${index + 1} 列</th>`,
  ).join('')}</tr>`;

  const rows = board.grid
    .map(
      (line, index) =>
        `<tr><th class="seat-row-head">第 ${index + 1} 排</th>${line.map(cellHtml).join('')}</tr>`,
    )
    .join('');

  const unseated = board.unseated.length
    ? `<div class="seat-unseated">
        <div class="muted">还没排座（${board.unseated.length} 人）</div>
        ${board.unseated
          .map(
            (student) =>
              `<button class="btn btn-sm${
                picked?.kind === 'student' && picked.studentId === student.studentId ? ' btn-primary' : ''
              }" type="button" data-student="${student.studentId}" data-name="${esc(student.studentName)}">
                ${esc(student.studentName)}</button>`,
          )
          .join('')}
      </div>`
    : '<div class="seat-unseated muted">全班都排上座了</div>';

  return `<div class="board">
    <div class="board-head">
      <span class="board-title">座位表</span>
      <span class="muted">${board.rows} 排 × ${board.cols} 列 · 已坐 ${board.seated} 人</span>
      <button class="btn btn-sm" type="button" data-act="plan">改大小</button>
      <button class="btn btn-sm" type="button" data-act="shift">轮换</button>
      <button class="btn btn-sm" type="button" data-act="randomize">随机排位</button>
      <button class="btn btn-sm" type="button" data-act="restore"${board.canRestore ? '' : ' disabled'}>回退</button>
      <button class="btn btn-sm btn-ghost" type="button" data-act="clear">清空</button>
    </div>
    <div class="board-note muted">排位原则：${esc(board.rule || '（没写）')}</div>
    <div class="seat-layout">
      <div class="seat-grid-wrap">
        <div class="seat-podium">讲　台</div>
        <table class="seat-grid"><thead>${head}</thead><tbody>${rows}</tbody></table>
      </div>
      ${unseated}
    </div>
    <div class="board-note muted" data-hint>${hintHtml()}</div>
  </div>`;
}

/* ---------------------------------------------------------------- 弹窗 */

function openPlanEditor(board, onDone) {
  openModal({
    title: '座位表大小与排位原则',
    body: `<div class="form-grid">
        <div class="field"><label>排数</label>
          <input class="input" type="number" min="1" max="20" data-rows value="${board.rows}"></div>
        <div class="field"><label>列数</label>
          <input class="input" type="number" min="1" max="16" data-cols value="${board.cols}"></div>
        <div class="field full"><label>排位原则</label>
          <textarea class="textarea" rows="3" data-rule>${esc(board.rule || '')}</textarea>
          <div class="hint">这段字是写给自己看的说明，随机排位不看它。</div></div>
      </div>
      <div class="muted">缩小到放不下现有座位时会被拒绝 —— 免得座位被挪到格子外面、看不见但还在。</div>`,
    footer: `<button class="btn" type="button" data-cancel>取消</button>
      <button class="btn btn-primary" type="button" data-ok>保存</button>`,
    onMount(root) {
      root.querySelector('[data-cancel]').addEventListener('click', closeModal);
      root.querySelector('[data-ok]').addEventListener('click', async () => {
        try {
          await api.seatPlan(
            {
              rows: Number(root.querySelector('[data-rows]').value),
              cols: Number(root.querySelector('[data-cols]').value),
              rule: root.querySelector('[data-rule]').value,
            },
            store.currentClassId,
          );
          toast('已保存');
          closeModal();
          onDone();
        } catch (error) {
          toast(error.message, 'err', 8000);
        }
      });
    },
  });
}

function openShiftDialog(onDone) {
  openModal({
    title: '整体轮换',
    body: `<div class="field"><label>方向</label>
        <select class="select" data-direction>
          ${DIRECTIONS.map(([value, label]) => `<option value="${value}">${label}</option>`).join('')}
        </select></div>
      <div class="field" style="margin-top:10px"><label>移动几格</label>
        <input class="input" type="number" min="1" max="20" data-step value="1"></div>
      <div class="muted">锁定座位不动；越界会绕回另一侧。做完可以点「回退」还原。</div>`,
    footer: `<button class="btn" type="button" data-cancel>取消</button>
      <button class="btn btn-primary" type="button" data-ok>开始轮换</button>`,
    onMount(root) {
      root.querySelector('[data-cancel]').addEventListener('click', closeModal);
      root.querySelector('[data-ok]').addEventListener('click', async () => {
        try {
          const data = await api.seatShift(
            root.querySelector('[data-direction]').value,
            Number(root.querySelector('[data-step]').value),
            store.currentClassId,
          );
          toast(`已轮换 ${data.moved} 个座位`);
          closeModal();
          onDone(data);
        } catch (error) {
          toast(error.message, 'err', 7000);
        }
      });
    },
  });
}

/* ---------------------------------------------------------------- 面板 */

export const seatPanel = {
  async html() {
    try {
      lastBoard = await api.seatBoard(store.currentClassId);
      return boardHtml(lastBoard);
    } catch (error) {
      return `<div class="board muted">座位表没取到数据：${esc(error.message)}</div>`;
    }
  },

  bind(root, ctx) {
    /** 用服务端返回的看板数据就地重绘（批量接口都会带上新看板，省一次往返）。 */
    function paint(board) {
      if (board) lastBoard = board;
      const area = root.querySelector('[data-panel]');
      if (area && lastBoard) area.innerHTML = boardHtml(lastBoard);
    }

    root.addEventListener('click', async (event) => {
      const action = event.target.closest('[data-act]');
      if (action) {
        await handleAction(action.dataset.act, paint, ctx);
        return;
      }

      const student = event.target.closest('[data-student]');
      if (student) {
        picked = {
          kind: 'student',
          studentId: Number(student.dataset.student),
          name: student.dataset.name,
        };
        paint();
        return;
      }

      const cell = event.target.closest('.seat-cell');
      if (cell) await handleCell(cell, paint, ctx);
    });
  },
};

async function handleAction(name, paint, ctx) {
  if (name === 'cancel') {
    picked = null;
    paint();
    return;
  }

  if (name === 'randomize') {
    try {
      const data = await api.seatRandomize(store.currentClassId);
      picked = null;
      toast(
        `已随机排位 ${data.placed} 人` +
          (data.locked ? `（${data.locked} 个锁定座位没动）` : '') +
          (data.addedRows ? `，座位不够已加 ${data.addedRows} 排` : ''),
      );
      paint(data);
    } catch (error) {
      toast(error.message, 'err', 7000);
    }
    return;
  }

  if (name === 'shift') {
    openShiftDialog((data) => paint(data));
    return;
  }

  if (name === 'plan') {
    openPlanEditor(lastBoard, () => ctx.refresh());
    return;
  }

  if (name === 'restore') {
    const yes = await confirmBox('回到上一次批量操作之前？回退只能用一次。', { okText: '回退' });
    if (!yes) return;
    try {
      const data = await api.seatRestore(store.currentClassId);
      picked = null;
      toast(
        data.clearedSeats
          ? `已回退（${data.clearedSeats} 个座位的人已经不在学生档案里，按空位恢复）`
          : '已回退',
      );
      paint(data);
    } catch (error) {
      toast(error.message, 'err', 7000);
    }
    return;
  }

  if (name === 'clear') {
    const yes = await confirmBox('清空整张座位表？座位表大小留着，清空后可以回退一次。', {
      okText: '清空',
      danger: true,
    });
    if (!yes) return;
    try {
      const data = await api.seatClear(store.currentClassId);
      picked = null;
      toast(data.removed ? `已清空 ${data.removed} 个座位` : '本来就是空的');
      paint(data);
    } catch (error) {
      toast(error.message, 'err', 7000);
    }
    return;
  }

  // 选中栏上的三个动作：作用于当前选中的那个座位
  if (!picked?.seatId) return;
  const seatId = picked.seatId;
  try {
    if (name === 'lock') {
      await api.update('seats', seatId, { locked: !picked.locked });
      toast(picked.locked ? '已解锁' : '已锁定（不参与随机与轮换）');
    } else if (name === 'edit') {
      await openForm(getSpec('seats'), await api.get('seats', seatId));
    } else {
      await api.remove('seats', seatId);
      toast('已腾空');
    }
    picked = null;
    ctx.refresh();
  } catch (error) {
    toast(error.message, 'err', 7000);
  }
}

async function handleCell(cell, paint, ctx) {
  const row = Number(cell.dataset.row);
  const col = Number(cell.dataset.col);
  const seatId = cell.dataset.seat ? Number(cell.dataset.seat) : null;

  if (picked?.kind === 'student') {
    if (seatId) {
      toast('这个格子上有人了。要换人请先点住座位上的人，再点目标格交换。', 'err', 6000);
      return;
    }
    try {
      await api.create(
        'seats',
        { row, col, student_name: picked.name },
        { classId: store.currentClassId },
      );
      toast(`已把 ${picked.name} 排到 ${row} 排 ${col} 列`);
      picked = null;
      ctx.refresh();
    } catch (error) {
      toast(error.message, 'err', 7000);
    }
    return;
  }

  if (!seatId) {
    toast('这是个空座位。先点左边的学生，再点它就能放人进去。');
    return;
  }

  if (picked?.seatId === seatId) {
    picked = null;
    paint();
    return;
  }

  if (picked) {
    try {
      const data = await api.seatSwap({ seatId: picked.seatId, row, col }, store.currentClassId);
      toast(data.swapped ? '已交换位置' : '已挪过去');
      picked = null;
      paint(data);
    } catch (error) {
      toast(error.message, 'err', 7000);
    }
    return;
  }

  const row_data = await api.get('seats', seatId).catch(() => null);
  if (!row_data) {
    toast('这个座位不存在，可能刚被删掉。刷新一下看看。', 'err', 6000);
    return;
  }
  picked = {
    kind: 'seat',
    seatId,
    name: row_data.student_name || '空座位',
    locked: Boolean(row_data.locked),
  };
  paint();
}
