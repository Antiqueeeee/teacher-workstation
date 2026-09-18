/**
 * 附件面板：一条记录的**照片与录音归档**。
 *
 * 用户提的第三个痛点就是它：「和家长沟通之后留档」。所以这里的重点不是花哨，
 * 而是**手机上做得动**：一个大按钮选文件（不拦格式，按 kind 自己判断），
 * 传完就能看到缩略图、能点开放大、录音能直接播。
 *
 * 两条照着后端能力来的规矩：
 * - 上传成功后**用服务端返回的元数据**渲染（尺寸/时长都是后端读的，前端不算）；
 * - 浏览器放不了的音频（手机上常见的 amr/aac）**不假装能播**，标出来给「下载后播放」。
 */

import { api } from '../core/api.js';
import { esc } from '../core/dom.js';
import { closeModal, confirmBox, openModal, toast } from './ui.js';

function itemHtml(item) {
  if (item.kind === 'image') {
    return `<figure class="media-item">
      <button type="button" data-view="${item.id}" title="${esc(item.originalName)}">
        <img src="${esc(item.thumbUrl)}" alt="${esc(item.originalName)}" loading="lazy">
      </button>
      <figcaption>
        <span class="media-name">${esc(item.originalName)}</span>
        <span class="muted">${esc(item.sizeText)}${item.width ? ` · ${item.width}×${item.height}` : ''}</span>
        <button class="btn btn-sm btn-ghost" type="button" data-del="${item.id}">删除</button>
      </figcaption>
    </figure>`;
  }
  if (item.kind === 'audio') {
    return `<div class="media-item media-audio">
      <div class="media-name">${esc(item.originalName)}</div>
      <div class="muted">${esc(item.sizeText)}${item.durationText ? ` · ${esc(item.durationText)}` : ''}
        ${item.playable ? '' : ' · 这个格式浏览器放不了，请下载后播放'}</div>
      ${
        item.playable
          ? `<audio controls preload="none" src="${esc(item.fileUrl)}"></audio>`
          : `<a class="btn btn-sm" href="${esc(item.fileUrl)}" download>下载后播放</a>`
      }
      <div><button class="btn btn-sm btn-ghost" type="button" data-del="${item.id}">删除</button></div>
    </div>`;
  }
  if (item.kind === 'video') {
    return `<div class="media-item media-audio">
      <div class="media-name">${esc(item.originalName)}</div>
      <div class="muted">${esc(item.sizeText)}${item.durationText ? ` · ${esc(item.durationText)}` : ''}</div>
      <video controls preload="metadata" src="${esc(item.fileUrl)}"></video>
      <div><button class="btn btn-sm btn-ghost" type="button" data-del="${item.id}">删除</button></div>
    </div>`;
  }
  return `<div class="media-item media-doc">
    <div class="media-name">${esc(item.originalName)}</div>
    <div class="muted">${esc(item.sizeText)}</div>
    <a class="btn btn-sm" href="${esc(item.fileUrl)}" download>下载</a>
    <button class="btn btn-sm btn-ghost" type="button" data-del="${item.id}">删除</button>
  </div>`;
}

function hintHtml() {
  return `归档的照片与录音存放在<strong>你自己的电脑上</strong>，不会上传到任何第三方。
    请勿上传与工作无关的内容；建议沟通结束后 3 个月内清理录音。`;
}

export function openMediaPanel({ ownerTable, ownerId, title = '附件', onChanged } = {}) {
  openModal({
    title: `${esc(title)} · 照片与录音`,
    wide: true,
    body: `
      <div class="media-toolbar">
        <label class="btn btn-primary" for="media-input">选文件上传</label>
        <input id="media-input" type="file" multiple accept="image/*,audio/*,video/*,.pdf"
          data-input hidden>
        <span class="muted" data-hint>照片、录音、视频都可以；手机拍的、手机录的都能直接传</span>
      </div>
      <div class="media-list" data-list><div class="muted">正在载入…</div></div>
      <div class="board-note muted">${hintHtml()}</div>`,
    footer: '<button class="btn" type="button" data-cancel>关闭</button>',
    onMount(root) {
      const listArea = root.querySelector('[data-list]');
      const hint = root.querySelector('[data-hint]');
      const input = root.querySelector('[data-input]');
      let items = [];

      root.querySelector('[data-cancel]').addEventListener('click', closeModal);

      function render() {
        listArea.innerHTML = items.length
          ? items.map(itemHtml).join('')
          : '<div class="muted">还没有附件。点上面的「选文件上传」把照片或录音放进来。</div>';
      }

      async function load() {
        try {
          items = await api.mediaList(ownerTable, ownerId);
        } catch (error) {
          listArea.innerHTML = `<div class="muted">附件没取到：${esc(error.message)}</div>`;
          return;
        }
        render();
      }

      async function upload(files) {
        const pending = Array.from(files || []);
        if (!pending.length) return;
        let done = 0;
        for (const file of pending) {
          hint.textContent = `正在上传 ${file.name}（${done + 1}/${pending.length}）…`;
          try {
            await api.mediaUpload(ownerTable, ownerId, file);
            done += 1;
          } catch (error) {
            // 单个文件失败不打断整批：说清是哪个文件、为什么
            toast(`${file.name}：${error.message}`, 'err', 9000);
          }
        }
        hint.textContent = done ? `已上传 ${done} 个文件` : '照片、录音、视频都可以';
        await load();
        if (done && onChanged) onChanged();
      }

      input.addEventListener('change', async () => {
        await upload(input.files);
        input.value = ''; // 同一个文件再传一次也要能触发 change
      });

      listArea.addEventListener('click', async (event) => {
        const view = event.target.closest('[data-view]');
        if (view) {
          const item = items.find((entry) => String(entry.id) === view.dataset.view);
          if (item) openLightbox(item);
          return;
        }

        const del = event.target.closest('[data-del]');
        if (!del) return;
        const item = items.find((entry) => String(entry.id) === del.dataset.del);
        const yes = await confirmBox(
          `删除附件「${esc(item?.originalName || '')}」？文件会先进回收站（在数据目录的 trash 里），可以恢复。`,
          { okText: '删除', danger: true },
        );
        if (!yes) return;
        try {
          // media 不在注册表里，只有专用删除接口。**不能先试通用接口**：
          // 那是同一个请求，真正的错误会被第二次 404 顶掉，老师看到的是
          // 「这个附件不存在」而不是真实原因（评审指出的）
          await api.mediaDelete(del.dataset.del);
          toast('已删除，文件在回收站里');
          await load();
          if (onChanged) onChanged();
        } catch (error) {
          toast(error.message, 'err', 7000);
        }
      });

      load();
    },
  });
}

/** 图片灯箱：点缩略图看大图（用 1200 档缩略图，不是原件，省流量）。 */
function openLightbox(item) {
  openModal({
    title: esc(item.originalName),
    wide: true,
    body: `<div class="media-lightbox">
      <img src="${esc(item.largeUrl)}" alt="${esc(item.originalName)}">
      <div class="muted">${esc(item.sizeText)}${item.width ? ` · ${item.width}×${item.height}` : ''}
        · <a href="${esc(item.fileUrl)}" download>下载原件</a></div>
    </div>`,
    footer: '<button class="btn" type="button" data-cancel>关闭</button>',
    onMount(root) {
      root.querySelector('[data-cancel]').addEventListener('click', closeModal);
    },
  });
}
