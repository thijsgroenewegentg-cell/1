/**
 * Landing page DOM test: loads the REAL index.html + landing.js (jsdom)
 * and verifies the product page structure + the looping hero demo.
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
  check('landing: h1 tagline', /Say it once/.test(document.querySelector('h1').textContent));
  check('landing: hero sub', document.querySelector('.hero-sub').textContent.length > 60);
  check('landing: 2 CTAs', document.querySelectorAll('.hero-cta a').length === 2);
  check('landing: demo link points to the app',
    document.querySelector('.hero-cta .btn-primary').getAttribute('href') === 'app.html');
  const links = [...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href'))
    .filter(h => !h.startsWith('http') && !h.startsWith('#'));
  const allLocalExist = links.every(h => fs.existsSync(path.join(ROOT, h.split('#')[0])));
  check('landing: all local links resolve (' + links.length + ' links)', allLocalExist, links.filter(h => !fs.existsSync(path.join(ROOT, h.split('#')[0]))).join());
  check('landing: 6 feature cards', document.querySelectorAll('#features .card').length === 6);
  check('landing: 3 install cards', document.querySelectorAll('.install-card').length === 3);
  check('landing: privacy mentioned', /never leave|local storage|100% local/i.test(document.body.textContent));
  check('landing: JSON sample shown', /"action"/.test(document.querySelector('.how-json').textContent));
  check('landing: hero image exists', fs.existsSync(path.join(ROOT, 'site/hero.png')));

  // hero demo actually runs
  await sleep(600);
  check('demo: title typing into hero card', /[A-Za-z]/.test(document.getElementById('demoTitle').textContent));

  console.log(fails === 0 ? '\nALL LANDING TESTS PASSED' : `\n${fails} LANDING FAILURES`);
  process.exit(fails ? 1 : 0);
})().catch(e => { console.error('CRASH:', e); process.exit(1); });
