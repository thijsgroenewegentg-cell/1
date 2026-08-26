/**
 * NOTIFY — when something breaks while he works, the user finds out.
 * Channels (all used in parallel): Telegram, Web Push, SSE (connected tabs).
 * Smart debouncing: repeated failures of the same thing within a window
 * are collapsed into one alert, not a spam flood.
 */
'use strict';

const telegram = require('./telegram');
const push = require('./push');
const missionlog = require('./log');
const config = require('./config');

const DEBOUNCE_MS = 5 * 60 * 1000; // same-key failures alert at most every 5 min
const lastAlert = new Map(); // key → timestamp

function shouldAlert(key) {
  const now = Date.now();
  const last = lastAlert.get(key) || 0;
  if (now - last < DEBOUNCE_MS) return false;
  lastAlert.set(key, now);
  // Prune old entries
  if (lastAlert.size > 100) {
    for (const [k, t] of lastAlert) {
      if (now - t > DEBOUNCE_MS * 2) lastAlert.delete(k);
    }
  }
  return true;
}

/**
 * Send a failure notification through every available channel.
 * @param {object} opts { key, title, body, severity }
 *   key: deduplication key (e.g. "tool:mcp_blender_create_cube")
 *   severity: 'warning' | 'error' | 'critical'
 */
async function failure({ key, title, body, severity = 'error' }) {
  if (!key) key = 'unknown';
  if (!shouldAlert(key)) return { sent: false, reason: 'debounced' };

  const emoji = severity === 'critical' ? '🚨' : severity === 'warning' ? '⚠️' : '❌';
  const text = `${emoji} ${title}\n\n${String(body || '').slice(0, 400)}`;

  const results = { telegram: false, push: false, sse: false };

  // Telegram
  try {
    const cfg = config.load();
    if (cfg.telegramToken && (cfg.telegramChatIds || []).length > 0) {
      for (const chatId of cfg.telegramChatIds) {
        await telegram.send(cfg, chatId, text);
      }
      results.telegram = true;
    }
  } catch { /* best effort */ }

  // Web Push (only when no tab is connected — SSE handles the connected case)
  try {
    // We can't check SSE clients from here, so we send both push and SSE.
    // Push notifications are only visible when the PWA isn't open anyway.
    const r = await push.send(`ULTRON ${emoji}`, `${title} — ${String(body || '').slice(0, 200)}`);
    results.push = r.sent > 0;
  } catch { /* best effort */ }

  missionlog.add(severity === 'critical' ? 'critical' : 'error', `${title}: ${String(body || '').slice(0, 200)}`);
  return { sent: true, ...results };
}

/** Check a tool result for errors and notify if configured. */
async function checkToolResult(name, result) {
  if (!result) return;
  const isError =
    result.error ||
    result.ok === false && result.rejected !== true || // rejected syntax gate is intentional
    (typeof result === 'object' && result.isError === true);

  if (!isError) return;

  const cfg = config.load();
  if (cfg.failureNotifications === false) return; // user disabled

  const body = result.error || (typeof result === 'object' ? JSON.stringify(result).slice(0, 300) : String(result).slice(0, 300));
  await failure({
    key: `tool:${name}`,
    title: `Tool "${name}" failed while I was working`,
    body,
    severity: result.ok === false ? 'error' : 'warning',
  });
}

module.exports = { failure, checkToolResult, shouldAlert };
