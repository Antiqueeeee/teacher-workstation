/**
 * 班级费用看板：一个收费项目一张卡（应收/已收/未缴 + 余额），点开看明细与催缴名单。
 *
 * 卡片上的数字全部来自后端 `/fees/overview` —— 状态（已缴/部分/未缴/免缴）是**推导值**，
 * 只在一处算（`services/fee_service.py:status_of`）。旧应用只在前端算状态，
 * 于是导出文件里没有这一列、导入回来也认不出来，两边迟早对不上。
 */

import { api } from '../core/api.js';
import { esc } from '../core/dom.js';
import { errorCard } from '../core/errors.js';
import { store } from '../core/store.js';
import { closeModal, openModal, toast } from './ui.js';

const yuan = (cents) => `${(Number(cents || 0) / 100).toFixed(2)}`;

function cardHtml(item) {
  const counts = item.counts || {};
  const unpaid = (counts['未缴'] || 0) + (counts['部分'] || 0);
  return `<div class="fee-card">
    <div class="fee-card-head">
      <strong>${esc(item.name)}</strong>
      <span class="muted">每人 ${yuan(item.amountCents)} 元</span>
    </div>
    <div class="archive-stats">
      <span>应收 <strong>${yuan(item.expectedCents)}</strong></span>
      <span>已收 <strong>${yuan(item.collectedCents)}</strong></span>
      <span>未收 <strong>${yuan(item.owedCents)}</strong></span>
    </div>
    <div class="muted">${item.studentCount} 人
      ${unpaid ? `<span class="badge badge-beak">${unpaid} 人没缴齐</span>` : '<span class="badge badge-mint">都缴齐了</span>'}
      · 余额 ${yuan(item.ledger.balanceCents)} 元</div>
    <div class="toolbar" style="margin:8px 0 0">
      <button class="btn btn-sm" type="button" data-detail="${item.categoryId}">明细与催缴</button>
    </div>
  </div>`;
}

export const feePanel = {
  async html() {
    try {
      const data = await api.feeOverview(store.currentClassId);
      if (!data.categories.length) {
        return `<div class="board">
          <div class="board-head"><span class="board-title">班级费用</span></div>
          <div class="muted">还没有收费项目。在下面「新增」里加一个（填费用名称与每人应缴），
            再把每个学生的缴费记录录进来。</div>
        </div>`;
      }
      return `<div class="board">
        <div class="board-head"><span class="board-title">班级费用</span>
          <span class="muted">应收 ${yuan(data.totals.expectedCents)} · 已收 ${yuan(data.totals.collectedCents)}
            · 未收 ${yuan(data.totals.owedCents)} · 余额 ${yuan(data.totals.balanceCents)} 元</span></div>
        <div class="fee-grid">${data.categories.map(cardHtml).join('')}</div>
      </div>`;
    } catch (error) {
      return `<div class="board muted">班级费用没取到数据：${esc(error.message)}</div>`;
    }
  },

  bind(root, ctx) {
    root.addEventListener('click', async (event) => {
      const button = event.target.closest('[data-detail]');
      if (!button) return;
      try {
        const detail = await api.feeCategory(button.dataset.detail);
        openDetail(detail, ctx);
      } catch (error) {
        toast(error.message, 'err', 6000);
      }
    });
  },
};

function openDetail(detail, ctx) {
  const owing = detail.owing.length
    ? `<ul class="plain-list">${detail.owing
        .map(
          (row) =>
            `<li>${esc(row.studentName)} —— 应缴 ${yuan(row.shouldPayCents)}、已缴 ${yuan(row.paidCents)}
              <strong>还差 ${yuan(row.owedCents)}</strong>（${esc(row.status)}）</li>`,
        )
        .join('')}</ul>`
    : '<div class="muted">没有欠缴的</div>';

  openModal({
    title: `费用明细 · ${esc(detail.name)}`,
    wide: true,
    body: `
      <div class="archive-stats">
        <span>应收 <strong>${yuan(detail.expectedCents)}</strong></span>
        <span>已收 <strong>${yuan(detail.collectedCents)}</strong></span>
        <span>未收 <strong>${yuan(detail.owedCents)}</strong></span>
        <span>流水余额 <strong>${yuan(detail.ledger.balanceCents)}</strong></span>
      </div>
      <div class="muted">已缴 ${detail.counts['已缴'] || 0} · 部分 ${detail.counts['部分'] || 0}
        · 未缴 ${detail.counts['未缴'] || 0} · 免缴 ${detail.counts['免缴'] || 0}</div>
      <div class="archive-section"><div class="archive-section-head"><strong>催缴名单</strong>
        <span class="muted">按欠额排</span></div>${owing}</div>
      ${
        detail.missing.length
          ? `<div class="archive-section"><div class="archive-section-head"><strong>还没建缴费记录的学生</strong>
               <span class="muted">${detail.missing.length} 人</span></div>
              <div class="muted">${esc(detail.missing.join('、'))}</div></div>`
          : ''
      }
      <div class="archive-section"><div class="archive-section-head"><strong>改每人应缴标准</strong></div>
        <div class="toolbar" style="margin:0">
          <input class="input" type="number" step="0.01" min="0" style="width:120px"
            data-amount value="${yuan(detail.amountCents)}">
          <label class="checkbox-row"><input type="checkbox" data-backfill>
            <span class="muted">同时回填历史记录（只回填一分钱没缴过的）</span></label>
          <button class="btn btn-sm" type="button" data-save-amount>保存</button>
        </div>
        <div class="muted">默认不改历史记录 —— 应缴是收钱那一刻的约定。</div>
      </div>`,
    footer: '<button class="btn" type="button" data-cancel>关闭</button>',
    onMount(root) {
      root.querySelector('[data-cancel]').addEventListener('click', closeModal);
      root.querySelector('[data-save-amount]').addEventListener('click', async () => {
        const amountCents = Math.round(Number(root.querySelector('[data-amount]').value || 0) * 100);
        try {
          const result = await api.feeSetAmount(detail.categoryId, amountCents, root.querySelector('[data-backfill]').checked);
          toast(
            result.backfilled
              ? `已改标准，并回填 ${result.backfilled} 条还没缴过钱的记录`
              : '已改标准（历史记录不动）',
          );
          closeModal();
          ctx.refresh();
        } catch (error) {
          toast(error.message, 'err', 7000);
        }
      });
    },
  });
}
