/**
 * BROWSER — Ultron's window to the graphical web, via Playwright (opt-in).
 * Enable:  npm install playwright && npx playwright install chromium
 * One persistent headless Chromium context is reused across tool calls.
 */
'use strict';

let playwright = null;
let context = null;
let launching = null;

async function available() {
  try {
    if (!playwright) playwright = require('playwright');
    return true;
  } catch {
    return false;
  }
}

async function getContext() {
  if (context) return context;
  if (launching) return launching;
  launching = (async () => {
    if (!playwright) playwright = require('playwright');
    const browser = await playwright.chromium.launch({ headless: true });
    context = await browser.newContext({
      userAgent: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36',
      viewport: { width: 1280, height: 900 },
    });
    context.setDefaultTimeout(15000);
    return context;
  })();
  try {
    return await launching;
  } finally {
    launching = null;
  }
}

async function withPage(fn) {
  const ctx = await getContext();
  const pages = ctx.pages();
  const page = pages.length > 0 ? pages[0] : await ctx.newPage();
  return fn(page);
}

/**
 * Execute a browser action.
 * @param {object} a { action, url?, selector?, text?, key? }
 */
async function execute(a) {
  const action = String(a.action || '').toLowerCase();
  switch (action) {
    case 'open': {
      let parsed;
      try { parsed = new URL(a.url); } catch { return { error: `invalid URL: ${a.url}` }; }
      if (!/^https?:$/.test(parsed.protocol)) return { error: 'only http/https' };
      return withPage(async (page) => {
        const res = await page.goto(a.url, { waitUntil: 'domcontentloaded', timeout: 20000 });
        const title = await page.title().catch(() => '');
        const text = (await page.innerText('body').catch(() => '') || '').replace(/\s+/g, ' ').trim();
        return { ok: true, status: res ? res.status() : null, title, text: text.slice(0, 4000), url: page.url() };
      });
    }
    case 'read': {
      return withPage(async (page) => {
        const text = a.selector
          ? (await page.innerText(a.selector).catch(() => '')) 
          : (await page.innerText('body').catch(() => ''));
        return { ok: true, url: page.url(), text: String(text).replace(/\s+/g, ' ').trim().slice(0, 5000) };
      });
    }
    case 'click': {
      return withPage(async (page) => {
        await page.click(a.selector, { timeout: 10000 });
        await page.waitForLoadState('domcontentloaded').catch(() => {});
        const text = (await page.innerText('body').catch(() => '')).replace(/\s+/g, ' ').trim();
        return { ok: true, url: page.url(), text: text.slice(0, 2000) };
      });
    }
    case 'type': {
      return withPage(async (page) => {
        await page.fill(a.selector, String(a.text || ''), { timeout: 10000 });
        return { ok: true, url: page.url(), typed: String(a.text || '').slice(0, 200) };
      });
    }
    case 'press': {
      return withPage(async (page) => {
        await page.keyboard.press(String(a.key || 'Enter'));
        await page.waitForTimeout(400);
        const text = (await page.innerText('body').catch(() => '')).replace(/\s+/g, ' ').trim();
        return { ok: true, url: page.url(), text: text.slice(0, 2000) };
      });
    }
    case 'screenshot': {
      return withPage(async (page) => {
        const fs = require('fs');
        const path = require('path');
        const dir = path.join(__dirname, '..', 'data', 'files');
        fs.mkdirSync(dir, { recursive: true });
        const file = path.join(dir, `screenshot-${Date.now()}.png`);
        await page.screenshot({ path: file, fullPage: false });
        return { ok: true, saved: `data/files/${path.basename(file)}`, note: 'the user can view this; you may describe the page from the text you already read' };
      });
    }
    default:
      return { error: `unknown action "${action}" — use open, read, click, type, press or screenshot` };
  }
}

module.exports = { available, execute };
