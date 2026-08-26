/**
 * TELEGRAM — reach Ultron from anywhere. Long-poll-free simple polling:
 * the server ticks getUpdates every few seconds, runs the full agent
 * headlessly, and replies. Pairing: the first chat to message the bot
 * is bound automatically; others can be added in Settings.
 */
'use strict';

function base(cfg) {
  const url = String(cfg.telegramUrl || '').trim().replace(/\/+$/, '');
  return /^https?:\/\//i.test(url) ? url : 'https://api.telegram.org';
}

async function call(cfg, method, body) {
  if (!cfg.telegramToken) throw new Error('no telegram token configured');
  const res = await fetch(`${base(cfg)}/bot${cfg.telegramToken}/${method}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) {
    throw new Error(`telegram ${method} failed: ${res.status} ${String(data.description || '').slice(0, 160)}`);
  }
  return data.result;
}

/** Poll once; returns [{update_id, message}] and the next offset. */
async function tick(cfg, offset) {
  const updates = await call(cfg, 'getUpdates', {
    offset,
    timeout: 0,
    allowed_updates: ['message'],
  }).catch(() => []);
  let next = offset;
  const messages = [];
  for (const u of updates || []) {
    next = Math.max(next, (u.update_id || 0) + 1);
    if (u.message && u.message.chat && (u.message.text || (u.message.voice && u.message.voice.file_id))) messages.push(u.message);
  }
  return { messages, next };
}

/** Send a text message (auto-chunked to Telegram's 4096-char limit). */
async function send(cfg, chatId, text) {
  const clean = String(text || '').trim() || '…';
  const chunks = [];
  for (let i = 0; i < clean.length; i += 3800) chunks.push(clean.slice(i, i + 3800));
  for (const chunk of chunks.slice(0, 4)) {
    await call(cfg, 'sendMessage', { chat_id: chatId, text: chunk, disable_web_page_preview: true });
  }
  return { ok: true, chunks: Math.min(chunks.length, 4) };
}

/** Download a file (voice notes) → Buffer. */
async function downloadFile(cfg, fileId) {
  const info = await call(cfg, 'getFile', { file_id: fileId });
  if (!info || !info.file_path) throw new Error('telegram getFile returned no path');
  const res = await fetch(`${base(cfg)}/file/bot${cfg.telegramToken}/${info.file_path}`);
  if (!res.ok) throw new Error(`telegram download failed: ${res.status}`);
  const buf = Buffer.from(await res.arrayBuffer());
  if (buf.length > 20 * 1024 * 1024) throw new Error('voice file too large');
  return buf;
}

function parseChatIds(raw) {
  const list = Array.isArray(raw) ? raw : String(raw || '').split(',');
  return list.map((x) => String(x).trim()).filter((x) => /^-?\d{3,}$/.test(x)).slice(0, 10);
}

module.exports = { tick, send, downloadFile, parseChatIds, base };
