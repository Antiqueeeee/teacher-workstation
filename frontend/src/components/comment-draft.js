/**
 * 评语草稿：把学生这学期的痕迹拼成一段**可编辑**的初稿。
 *
 * 草稿是**事实陈述**，不是固定的抒情模板（旧应用的模板写死了「像春日的竹笋一节节拔高」
 * 这类句子，套在谁身上都一样）。评语是老师对学生说的话，模板腔反而帮倒忙 ——
 * 所以这里给的是数据与事实，语气由老师自己把关。
 *
 * 末尾固定「请人工复核」；特殊体质那条标了「只给你看，别写进评语」。
 */

import { api } from '../core/api.js';
import { esc } from '../core/dom.js';
import { errorCard } from '../core/errors.js';
import { closeModal, openModal, toast } from './ui.js';

export async function openCommentDraft(student) {
  openModal({
    title: `评语草稿 · ${esc(student?.name || '')}`,
    wide: true,
    body: '<div data-draft class="muted">正在生成…</div>',
    footer: `
      <button class="btn" type="button" data-copy>复制全文</button>
      <button class="btn" type="button" data-cancel>关闭</button>`,
    onMount(root) {
      const area = root.querySelector('[data-draft]');
      root.querySelector('[data-cancel]').addEventListener('click', closeModal);

      api
        .commentDraft(student.id)
        .then((data) => {
          area.innerHTML = `
            <div class="muted">下面每一段都按记录拼出来（出勤/作业/成绩/纪律/沟通…），
              可以直接在上面改写 —— 语气与措辞请你自己把关。</div>
            <textarea class="textarea" rows="10" data-text>${esc(data.draft)}</textarea>
            <div class="muted">${esc(data.review)}</div>
            <div class="archive-section">
              <div class="archive-section-head"><strong>各段依据</strong>
                <span class="muted">哪一段不对，就去对应模块改记录</span></div>
              <ul class="plain-list">
                ${data.dimensions
                  .map(
                    (item) =>
                      `<li><strong>${esc(item.label)}</strong>${item.teacherOnly ? '<span class="badge badge-rose">只给你看</span>' : ''}
                        ${esc(item.text)}</li>`,
                  )
                  .join('')}
              </ul>
            </div>`;

          root.querySelector('[data-copy]').addEventListener('click', async () => {
            const text = root.querySelector('[data-text]').value;
            try {
              await navigator.clipboard.writeText(text);
              toast('已复制');
            } catch {
              // 剪贴板要 https 或 localhost；局域网 http 下拿不到权限，就选中让老师自己复制
              const field = root.querySelector('[data-text]');
              field.focus();
              field.select();
              toast('已选中，按 Ctrl+C 复制', 'err', 6000);
            }
          });
        })
        .catch((error) => {
          area.innerHTML = errorCard(error);
        });
    },
  });
}
