/**
 * IMAGINE — local image generation via a Stable Diffusion server
 * (Automatic1111 / Forge / SD.Next all speak /sdapi/v1/txt2img).
 * Configure `sdUrl` in Settings. Free, offline.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const config = require('./config');

const DATA_DIR = process.env.ULTRON_DATA || path.join(__dirname, '..', 'data');
const OUT_DIR = path.join(DATA_DIR, 'files');

function sdBase() {
  const cfg = config.load();
  const url = String(cfg.sdUrl || '').trim().replace(/\/+$/, '');
  return /^https?:\/\//i.test(url) ? url : null;
}

/** Is a Stable Diffusion server configured and reachable? */
async function status() {
  const base = sdBase();
  if (!base) return { configured: false };
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 4000);
    const res = await fetch(base + '/sdapi/v1/options', { signal: controller.signal });
    clearTimeout(timer);
    if (!res.ok) return { configured: true, online: false, error: `HTTP ${res.status}` };
    return { configured: true, online: true };
  } catch (err) {
    return { configured: true, online: false, error: String(err.message || err).slice(0, 120) };
  }
}

/**
 * Generate an image from a prompt.
 * @param {object} a { prompt, negative_prompt?, width?, height?, steps? }
 */
async function generate(a) {
  const base = sdBase();
  if (!base) return { error: 'image generation not configured — set the Stable Diffusion URL in SETTINGS (Automatic1111 / Forge / SD.Next)' };

  const prompt = String(a.prompt || '').trim().slice(0, 1000);
  if (!prompt) return { error: 'no prompt given' };
  const width = Math.min(Math.max(parseInt(a.width, 10) || 768, 256), 1536);
  const height = Math.min(Math.max(parseInt(a.height, 10) || 768, 256), 1536);
  const steps = Math.min(Math.max(parseInt(a.steps, 10) || 25, 5), 60);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 180000); // local gen can be slow
  try {
    const res = await fetch(base + '/sdapi/v1/txt2img', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt,
        negative_prompt: String(a.negative_prompt || 'blurry, low quality, watermark, text'),
        width,
        height,
        steps,
        cfg_scale: 6.5,
        sampler_name: 'DPM++ 2M Karras',
      }),
      signal: controller.signal,
    });
    if (!res.ok) {
      const t = await res.text().catch(() => '');
      return { error: `Stable Diffusion responded ${res.status}: ${t.slice(0, 160)}` };
    }
    const data = await res.json();
    const b64 = (data.images || [])[0];
    if (!b64) return { error: 'no image returned' };

    fs.mkdirSync(OUT_DIR, { recursive: true });
    const file = `generated-${Date.now()}.png`;
    fs.writeFileSync(path.join(OUT_DIR, file), Buffer.from(b64.replace(/^data:image\/\w+;base64,/, ''), 'base64'));
    return {
      ok: true,
      saved: `data/files/${file}`,
      prompt,
      size: `${width}x${height}`,
      note: 'the image is shown to the user automatically — describe it briefly if useful',
    };
  } catch (err) {
    return { error: `image generation failed: ${err.name === 'AbortError' ? 'timeout (180s)' : String(err.message || err).slice(0, 140)}` };
  } finally {
    clearTimeout(timer);
  }
}

module.exports = { generate, status };
