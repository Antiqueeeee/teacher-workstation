/**
 * 宿舍分布看板：一间房一张卡，卡里是 N 个床位格子。
 *
 * 这里是「点空格子加人」那条路径的家。旧应用有三个加人入口（工具栏新增、点空格子、
 * 房间底部「增添住宿生」），每个各自处理容量与床号，同一个房间在不同入口下行为不同；
 * 这里只有一个入口，写入全部走后端那套校验（见 backend/app/services/dorm_service.py）。
 *
 * 三个交互：
 * - 点**空床位** → 选一个学生放进去（默认只列「住校但没床位」的人，也可以手输姓名）；
 * - 点**已占床位** → 看这个人 + 编辑记录 / 设为寝室长 / 腾空床位；
 * - 点房间标题旁的「N 人间」 → **模态框改容量**（旧应用这里是 `window.prompt()`，
 *   在禁用 prompt 的环境里直接静默什么都不做）。
 */

import { api } from '../core/api.js';
import { esc } from '../core/dom.js';
import { getSpec, store } from '../core/store.js';
import { openForm } from './form.js';
import { closeModal, confirmBox, openModal, toast } from './ui.js';

/* ---------------------------------------------------------------- 看板 */

function bedHtml(room, bed) {
  if (!bed.studentName) {
    return `<button class="dorm-bed empty" type="button"
      data-assign="${room.roomId}" data-bed-no="${bed.bedNo}">
      <span class="dorm-bed-no">${bed.bedNo}</span> 空
    </button>`;
  }
  return `<button class="dorm-bed${bed.orphan ? ' orphan' : ''}" type="button"
    data-bed-id="${bed.bedId}" data-room="${room.roomId}" data-bed-no="${bed.bedNo}"
    title="${esc(bed.note || '')}${bed.orphan ? '（学生已从档案删除）' : ''}">
    <span class="dorm-bed-no">${bed.bedNo}</span>
    <span class="dorm-bed-name">${esc(bed.studentName)}</span>
    ${bed.leader ? '<span class="badge badge-sun">长</span>' : ''}
  </button>`;
}

function roomHtml(room) {
  return `<div class="dorm-room">
    <div class="dorm-room-head">
      <strong>${esc(room.label)}</strong>
      <span class="muted">${room.occupied}/${room.capacity}</span>
      ${room.full ? '<span class="badge badge-ink">满</span>' : ''}
      <button class="btn btn-sm btn-ghost" type="button" data-capacity="${room.roomId}"
        data-cap="${room.capacity}" data-label="${esc(room.label)}"
        title="改容量（几人间）">✎ ${room.capacity} 人间</button>
    </div>
    <div class="dorm-beds">${room.beds.map((bed) => bedHtml(room, bed)).join('')}</div>
    ${room.note ? `<div class="muted">${esc(room.note)}</div>` : ''}
  </div>`;
}

export function boardHtml(tree) {
  if (!tree.rooms.length) {
    return `<div class="board">
      <div class="board-head"><span class="board-title">宿舍分布</span></div>
      <div class="muted">还没有房间。在下面「新增」里加一间（填楼栋、房号、几人间），
        或者把已有的宿舍表「导入」进来 —— 导入时房间不存在会自动建出来。</div>
    </div>`;
  }
  const unassigned = tree.unassigned;
  const fullRooms = tree.rooms.filter((room) => room.full);
  return `<div class="board">
    <div class="board-head">
      <span class="board-title">宿舍分布</span>
      <span class="muted">${tree.stats.roomCount} 间 · ${tree.stats.bedCount} 个床位 · 已住 ${tree.stats.occupied}</span>
      ${
        unassigned.length
          ? `<button class="btn btn-sm" type="button" data-unassigned>
               ${unassigned.length} 名住宿生还没床位
             </button>`
          : '<span class="badge badge-mint">住宿生都有床位了</span>'
      }
      ${
        fullRooms.length
          ? `<button class="btn btn-sm" type="button" data-full>${fullRooms.length} 间已住满</button>`
          : ''
      }
      <span class="muted">点空格子加人 · 点床位改人 · 点「N 人间」改容量</span>
    </div>
    <div class="dorm-grid">${tree.rooms.map(roomHtml).join('')}</div>
  </div>`;
}

/* ---------------------------------------------------------------- 分配 */

async function openAssign({ room, bedNo, unassigned, onDone }) {
  const candidates = unassigned
    .map(
      (student) => `<button class="btn btn-sm" type="button" data-pick="${esc(student.studentName)}">
        ${esc(student.studentName)}<span class="muted">${esc(student.sno || '')}</span>
      </button>`,
    )
    .join('');

  openModal({
    title: `把学生放进 ${esc(room.label)} 的 ${bedNo} 号床`,
    body: `
      ${
        candidates
          ? `<div class="muted">住校但还没有床位的（点一下就放进去）：</div>
             <div class="dorm-picks">${candidates}</div>`
          : '<div class="muted">没有「住了校但还没床位」的学生 —— 下面直接填姓名也行。</div>'
      }
      <div class="field" style="margin-top:12px">
        <label>学生姓名</label>
        <input class="input" type="text" data-name placeholder="也可以自己填姓名（或学号）">
        <div class="hint">填错了会明确报错，不会静默挂到同名的另一个人身上。</div>
      </div>`,
    footer: `
      <button class="btn" type="button" data-cancel>取消</button>
      <button class="btn btn-primary" type="button" data-ok>放进去</button>`,
    onMount(root) {
      const input = root.querySelector('[data-name]');
      root.querySelector('[data-cancel]').addEventListener('click', closeModal);

      async function assign(studentName) {
        const name = String(studentName || '').trim();
        if (!name) {
          toast('请填学生姓名', 'err', 4000);
          return;
        }
        try {
          await api.create(
            'dorm_beds',
            { building: room.building, room_no: room.roomNo, bed_no: bedNo, student_name: name },
            { classId: store.currentClassId },
          );
          toast(`已把 ${name} 放到 ${room.label} ${bedNo} 号床`);
          closeModal();
          if (onDone) onDone();
        } catch (error) {
          // 「这个学生已经有床位了」是日常操作（换床），所以给一条出口：
          // 直接改他**原来那条**床位记录的房间与床号 —— 一次请求、走同一套校验，
          // 比「先腾空再分配」少一步，也不会在中途失败时把人弄丢。
          if (error.code === 'DORM_STUDENT_ALREADY_ASSIGNED' && error.detail?.bedId) {
            const yes = await confirmBox(
              `${error.message}<br><br>要把他换到 <strong>${esc(room.label)} ${bedNo} 号床</strong>吗？`,
              { okText: '换过去' },
            );
            if (!yes) return;
            try {
              await api.update('dorm_beds', error.detail.bedId, {
                building: room.building,
                room_no: room.roomNo,
                bed_no: bedNo,
              });
              toast(`已把 ${name} 换到 ${room.label} ${bedNo} 号床`);
              closeModal();
              if (onDone) onDone();
            } catch (swapError) {
              toast(swapError.message, 'err', 8000);
            }
            return;
          }
          // 其余失败**不关弹窗**：老师能看到原因（床位被占/查无此人），改完直接重试
          toast(error.message, 'err', 8000);
        }
      }

      root.querySelectorAll('[data-pick]').forEach((button) => {
        button.addEventListener('click', () => assign(button.dataset.pick));
      });
      root.querySelector('[data-ok]').addEventListener('click', () => assign(input.value));
      input.focus();
    },
  });
}

/* ---------------------------------------------------------------- 床位操作 */

async function openBedActions({ row, onDone }) {
  const spec = getSpec('dorm_beds');
  openModal({
    title: `${esc(row.building || '')} ${esc(row.room_no)} ${row.bed_no} 号床`.trim(),
    body: `<div class="kpi-row" style="margin:0">
        <div class="kpi"><div class="kpi-value">${esc(row.student_name || '（空）')}</div>
          <div class="kpi-label">${esc(row.sno || '无学号')}</div></div>
        <div class="kpi"><div class="kpi-value">${row.leader ? '是' : '否'}</div><div class="kpi-label">寝室长</div></div>
        <div class="kpi"><div class="kpi-value">${esc(row.orphan ? '已删除' : '在册')}</div><div class="kpi-label">学生状态</div></div>
      </div>
      ${row.note ? `<div class="muted">备注：${esc(row.note)}</div>` : ''}
      ${
        row.orphan
          ? '<div class="muted">这个学生已经从学生档案里删掉了，床位还占着 —— 点「腾空床位」把它放出来。</div>'
          : ''
      }`,
    footer: `
      <button class="btn" type="button" data-edit>编辑记录</button>
      <button class="btn" type="button" data-rotate="${row.leader ? 'off' : 'on'}">
        ${row.leader ? '取消寝室长' : '设为寝室长'}
      </button>
      <button class="btn btn-danger" type="button" data-free>腾空床位</button>
      <button class="btn" type="button" data-cancel>关闭</button>`,
    onMount(root) {
      root.querySelector('[data-cancel]').addEventListener('click', closeModal);

      root.querySelector('[data-edit]').addEventListener('click', async () => {
        closeModal();
        const saved = await openForm(spec, row);
        if (saved && onDone) onDone();
      });

      root.querySelector('[data-rotate]').addEventListener('click', async (event) => {
        const leader = event.target.closest('[data-rotate]').dataset.rotate === 'on';
        try {
          await api.update('dorm_beds', row.id, { leader });
          toast(leader ? '已设为寝室长' : '已取消寝室长');
          closeModal();
          if (onDone) onDone();
        } catch (error) {
          toast(error.message, 'err', 6000);
        }
      });

      root.querySelector('[data-free]').addEventListener('click', async () => {
        const yes = await confirmBox(
          `腾空 ${esc(row.room_label || '')} ${row.bed_no} 号床？这一条床位记录会被删掉，学生从这张床上移除。`,
          { okText: '腾空', danger: true },
        );
        if (!yes) return;
        try {
          await api.remove('dorm_beds', row.id);
          toast('已腾空');
          closeModal();
          if (onDone) onDone();
        } catch (error) {
          toast(error.message, 'err', 6000);
        }
      });
    },
  });
}

/* ---------------------------------------------------------------- 改容量 */

async function openCapacity({ roomId, label, capacity, onDone }) {
  openModal({
    title: `改「${esc(label)}」的容量`,
    body: `
      <div class="field">
        <label>几人间</label>
        <input class="input" type="number" min="1" max="40" data-cap value="${capacity}">
        <div class="hint">
          住的人比容量多时会<strong>拒绝</strong>并告诉你里面住着谁 ——
          不会像旧版那样界面上直接少显示几个人。
        </div>
      </div>`,
    footer: `
      <button class="btn" type="button" data-cancel>取消</button>
      <button class="btn btn-primary" type="button" data-ok>保存</button>`,
    onMount(root) {
      const input = root.querySelector('[data-cap]');
      root.querySelector('[data-cancel]').addEventListener('click', closeModal);
      root.querySelector('[data-ok]').addEventListener('click', async () => {
        try {
          await api.update('dorm_rooms', roomId, { capacity: Number(input.value) });
          toast(`已设为 ${Number(input.value)} 人间`);
          closeModal();
          if (onDone) onDone();
        } catch (error) {
          toast(error.message, 'err', 9000);
        }
      });
      input.select();
    },
  });
}

/* ---------------------------------------------------------------- 未分配名单 */

function openUnassigned({ unassigned }) {
  openModal({
    title: '住宿但还没床位的学生',
    body: `<ul class="plain-list">${unassigned
      .map((student) => `<li>${esc(student.studentName)}<span class="muted">${esc(student.sno || '')}</span></li>`)
      .join('')}</ul>
      <div class="muted" style="margin-top:10px">
        这份名单按学生档案里的「住宿 = 住校」来算。要加人请回到看板上点空格子 ——
        床位不满时也能直接点。
      </div>`,
    footer: '<button class="btn" type="button" data-cancel>关闭</button>',
    onMount(root) {
      root.querySelector('[data-cancel]').addEventListener('click', closeModal);
    },
  });
}

function openFull({ fullRooms }) {
  openModal({
    title: '已住满的房间',
    body: `<ul class="plain-list">${fullRooms
      .map(
        (room) =>
          `<div>${esc(room.label)}<span class="muted"> ${room.occupied}/${room.capacity} 人</span></div>`,
      )
      .join('')}</div>
      <div class="muted" style="margin-top:10px">
        住满的房间要加人，得先把容量调大（点房间标题旁的「N 人间」）——
        旧版会在这种情况给出一个没人看得懂的报错。
      </div>`,
    footer: '<button class="btn" type="button" data-cancel>关闭</button>',
    onMount(root) {
      root.querySelector('[data-cancel]').addEventListener('click', closeModal);
    },
  });
}

/* ---------------------------------------------------------------- 面板 */

export const dormPanel = {
  async html() {
    try {
      const tree = await api.dormTree(store.currentClassId);
      return boardHtml(tree);
    } catch (error) {
      return `<div class="board muted">宿舍分布没取到数据：${esc(error.message)}</div>`;
    }
  },
  bind(root, ctx) {
    root.addEventListener('click', async (event) => {
      const assign = event.target.closest('[data-assign]');
      if (assign) {
        const tree = await api.dormTree(store.currentClassId);
        const room = tree.rooms.find((item) => item.roomId === Number(assign.dataset.assign));
        await openAssign({
          room,
          bedNo: Number(assign.dataset.bedNo),
          unassigned: tree.unassigned,
          onDone: ctx.refresh,
        });
        return;
      }

      const bed = event.target.closest('[data-bed-id]');
      if (bed) {
        try {
          const row = await api.get('dorm_beds', bed.dataset.bedId);
          await openBedActions({ row, onDone: ctx.refresh });
        } catch (error) {
          toast(error.message, 'err', 6000);
        }
        return;
      }

      const capacity = event.target.closest('[data-capacity]');
      if (capacity) {
        await openCapacity({
          roomId: Number(capacity.dataset.capacity),
          label: capacity.dataset.label,
          capacity: Number(capacity.dataset.cap),
          onDone: ctx.refresh,
        });
        return;
      }

      if (event.target.closest('[data-unassigned]')) {
        const tree = await api.dormTree(store.currentClassId);
        openUnassigned({ unassigned: tree.unassigned });
        return;
      }

      if (event.target.closest('[data-full]')) {
        const tree = await api.dormTree(store.currentClassId);
        openFull({ fullRooms: tree.rooms.filter((room) => room.full) });
      }
    });
  },
};
