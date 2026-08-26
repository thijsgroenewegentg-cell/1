/**
 * PUSH — Web Push notifications (VAPID), free, no server cost.
 * Subscriptions + keys live in data/push.json. Used to reach the user's
 * phone (installed PWA) when no browser tab is connected.
 */
'use strict';

const fs = require('fs');
const path = require('path');

const DATA_DIR = path.join(__dirname, '..', 'data');
const FILE = path.join(DATA_DIR, 'push.json');

let store = null; // { publicKey, privateKey, subscriptions: [{endpoint, keys}] }

function load() {
  if (store) return store;
  try {
    store = JSON.parse(fs.readFileSync(FILE, 'utf8'));
    if (!store.subscriptions) store.subscriptions = [];
  } catch {
    store = null;
  }
  return store;
}

function save() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.writeFileSync(FILE, JSON.stringify(store, null, 2));
}

function webpush() {
  return require('web-push');
}

/** Get or create the VAPID identity. */
function keys() {
  if (load()) return store;
  const generated = webpush().generateVAPIDKeys();
  store = { ...generated, subscriptions: [] };
  save();
  return store;
}

function publicKey() {
  return keys().publicKey;
}

function subscribe(subscription) {
  const s = keys();
  if (!subscription || !subscription.endpoint || !subscription.keys) {
    return { error: 'invalid subscription' };
  }
  const exists = s.subscriptions.some((x) => x.endpoint === subscription.endpoint);
  if (!exists) {
    s.subscriptions.push({ endpoint: subscription.endpoint, keys: subscription.keys });
    save();
  }
  return { ok: true, count: s.subscriptions.length };
}

function unsubscribe(endpoint) {
  const s = load();
  if (!s) return { ok: true };
  s.subscriptions = s.subscriptions.filter((x) => x.endpoint !== endpoint);
  save();
  return { ok: true };
}

/** Send a notification to every subscriber. Returns delivery stats. */
async function send(title, body) {
  const s = load();
  if (!s || s.subscriptions.length === 0) return { sent: 0, failed: 0, skipped: true };
  const wp = webpush();
  wp.setVapidDetails('mailto:ultron@localhost', s.publicKey, s.privateKey);
  let sent = 0;
  let failed = 0;
  const payload = JSON.stringify({ title, body, url: '/' });
  for (const sub of s.subscriptions.slice()) {
    try {
      await wp.sendNotification(sub, payload);
      sent++;
    } catch (err) {
      failed++;
      // 404/410 = subscription gone → prune it
      if (err && (err.statusCode === 404 || err.statusCode === 410)) {
        s.subscriptions = s.subscriptions.filter((x) => x.endpoint !== sub.endpoint);
        save();
      }
    }
  }
  return { sent, failed };
}

module.exports = { publicKey, subscribe, unsubscribe, send };
