/**
 * Landing page DOM test: loads the REAL index.html + landing.js (jsdom)
 * and verifies the replica structure + the EN/NL language switch.
 *
 *   node tests/landingtest.js
 */
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { console.log('SKIP  jsdom not installed'); process.exit(0); }

const fs = require('fs');
const path = require('path');
const ROOT = path.join(__dirname, '..');

const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8')
  .replace('<script src="landing.js"></script>',
           () => '<script>' + fs.readFileSync(path.join(ROOT, 'landing.js'), 'utf8') + '</script>');

const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true, url: 'https://localhost/' });
const { document } = dom.window;
const sleep = ms => new Promise(r => setTimeout(r, ms));

let fails = 0;
const check = (label, cond, extra) => {
  console.log((cond ? 'PASS' : 'FAIL') + '  ' + label + (cond ? '' : '  -> ' + extra));
  if (!cond) fails++;
};

(async () => {
  /* ---------- replica structure (mirrors reference flow) ---------- */
  check('structure: hero headline', /voice assistant|at your fingertips/i.test(document.querySelector('h1').textContent));
  check('structure: badge present', !!document.querySelector('.yc-badge'));
  check('structure: 2 CTAs', document.querySelectorAll('.hero-cta a').length === 2);
  check('structure: demo link → app', document.querySelector('.hero-cta .btn-primary').getAttribute('href') === 'app.html');
  check('structure: icon marquee built (48 tiles)', document.querySelectorAll('#marqueeTrack .tile').length === 48,
    document.querySelectorAll('#marqueeTrack .tile').length);
  check('structure: point/cursor section', /point anywhere/i.test(document.querySelector('.point h2').textContent));
  check('structure: productivity bars 1×/4×/10×',
    [...document.querySelectorAll('.pbar b')].map(b => b.textContent).join(',') === '1×,4×,10×');
  check('structure: voice-to-action chips (11)', document.querySelectorAll('.achip').length === 11);
  check('structure: strike-through speech-to-text', !!document.querySelector('.actions s'));
  check('structure: search rotator', !!document.getElementById('rotator'));
  check('structure: agent section', !!document.querySelector('.agent-sec'));
  check('structure: privacy toggles on (3) + optional off (1)',
    document.querySelectorAll('.toggle.on').length === 3 && document.querySelectorAll('.toggle:not(.on)').length === 1);
  check('structure: wall of love (3 quotes)', document.querySelectorAll('.love-card').length === 3);
  check('structure: hero image exists', fs.existsSync(path.join(ROOT, 'site/hero.png')));

  const links = [...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href'))
    .filter(h => !h.startsWith('http') && !h.startsWith('#'));
  check('structure: all local links resolve', links.every(h => fs.existsSync(path.join(ROOT, h.split('#')[0]))) ,
    links.join());

  /* ---------- EN/NL language switch ---------- */
  check('i18n: language toggle present', !!document.getElementById('langToggle'));
  document.getElementById('langToggle').click();
  await sleep(60);
  check('i18n: page switches to Dutch', document.body.dataset.lang === 'nl');
  check('i18n: hero title is Dutch', /Spraakassistent/.test(document.querySelector('h1').textContent), document.querySelector('h1').textContent);
  check('i18n: action chips are Dutch', /Beantwoord Maya/.test(document.body.textContent), '');
  check('i18n: toggle label flips to EN', document.getElementById('langToggle').textContent.includes('EN'));
  check('i18n: persisted', dom.window.localStorage.getItem('voiceos_site_lang') === 'nl');
  document.getElementById('langToggle').click();
  await sleep(60);
  check('i18n: back to English', document.body.dataset.lang === 'en' && /at your fingertips/.test(document.querySelector('h1').textContent));

  /* ---------- live demo actually animates ---------- */
  await sleep(700);
  check('demo: typing into hero card', /[A-Za-z]/.test(document.getElementById('demoTitle').textContent));

  console.log(fails === 0 ? '\nALL LANDING TESTS PASSED' : `\n${fails} LANDING FAILURES`);
  process.exit(fails ? 1 : 0);
})().catch(e => { console.error('CRASH:', e); process.exit(1); });
