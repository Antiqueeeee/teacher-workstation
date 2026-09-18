/**
 * 宿舍值日看板：一间房一张卡，卡里是周一到周日各自的安排。
 *
 * 为什么要有这一块：值日的记录是「房间 × 星期 × 任务」的散点，逐条列表很难回答
 * 「周三 203 谁值日」这种日常问题。旧应用也有分组卡片，但它是**前端把整表拉下来分组**——
 * 记录一多到分页就会少一块，而界面上看不出来。这里的 `days` 由后端分组给全。
 *
 * 点某天的「加」就是新增，房间与星期已经预填好（`openForm` 支持不带 id 的预填对象）。
 */

import { api } from '../core/api.js';
import { esc } from '../core/dom.js';
import { getSpec, store } from '../core/store.js';
import { openForm } from './form.js';
import { toast } from './ui.js';

const RESULT_CLASS = { 优秀: 'badge-mint', 合格: 'badge-ice', 待改进: 'badge-rose' };

function itemHtml(room, day, item) {
  return `<button class="duty-item" type="button" data-duty="${item.id}"
    title="${esc(item.note || '')}${item.orphan ? '（学生已从档案删除）' : ''}">
    <span class="duty-who${item.orphan ? ' orphan' : ''}">${esc(item.studentName || '（没填人）')}</span>
    <span class="duty-task">${esc(item.task || '')}</span>
    <span class="badge ${RESULT_CLASS[item.result] || 'badge-ink'}">${esc(item.result || '—')}</span>
  </button>`;
}

function dayHtml(room, day) {
  return `<div class="duty-day">
    <span class="duty-weekday">${esc(day.weekday)}</span>
    <div class="duty-items">
      ${day.items.map((item) => itemHtml(room, day, item)).join('')}
    </div>
    <button class="btn btn-sm btn-ghost" type="button"
      data-add="${room.roomId}" data-weekday="${esc(day.weekday)}"
      data-room-no="${esc(room.roomNo)}" data-building="${esc(room.building)}">＋</button>
  </div>`;
}

function roomHtml(room) {
  return `<div class="dorm-room duty-room">
    <div class="dorm-room-head">
      <strong>${esc(room.label)}</strong>
      <span class="muted">${room.count} 条安排</span>
    </div>
    <div class="duty-days">${room.days.map((day) => dayHtml(room, day)).join('')}</div>
  </div>`;
}

export function dutyBoardHtml(board) {
  if (!board.rooms.length) {
    return `<div class="board">
      <div class="board-head"><span class="board-title">宿舍值日</span></div>
      <div class="muted">还没有房间。先到「宿舍分布」加几间房，再回来排值日 ——
        值日安排里的房间必须是已经存在的房间（旧版能填一个不存在的房号）。</div>
    </div>`;
  }
  const orphans = board.orphanRooms || [];
  return `<div class="board">
    <div class="board-head">
      <span class="board-title">宿舍值日</span>
      <span class="muted">共 ${board.total} 条安排 · 点「＋」按天加人，点某条改它</span>
    </div>
    ${
      orphans.length
        ? `<div class="board-note muted">有 ${orphans.length} 间房已经不在宿舍分布里了
             （${esc(orphans.join('、'))}），它们的值日安排还在 —— 到列表里删掉，或把那间房加回来。</div>`
        : ''
    }
    <div class="dorm-grid">${board.rooms.map(roomHtml).join('')}</div>
  </div>`;
}

export const dutyPanel = {
  async html() {
    try {
      return dutyBoardHtml(await api.dutyBoard(store.currentClassId));
    } catch (error) {
      return `<div class="board muted">宿舍值日没取到数据：${esc(error.message)}</div>`;
    }
  },

  bind(root, ctx) {
    root.addEventListener('click', async (event) => {
      const add = event.target.closest('[data-add]');
      if (add) {
        const spec = getSpec('dorm_duties');
        const saved = await openForm(spec, {
          building: add.dataset.building,
          room_no: add.dataset.roomNo,
          weekday: add.dataset.weekday,
        });
        if (saved) ctx.refresh();
        return;
      }

      const item = event.target.closest('[data-duty]');
      if (item) {
        try {
          const row = await api.get('dorm_duties', item.dataset.duty);
          const saved = await openForm(getSpec('dorm_duties'), row);
          if (saved) ctx.refresh();
        } catch (error) {
          toast(error.message, 'err', 6000);
        }
      }
    });
  },
};
