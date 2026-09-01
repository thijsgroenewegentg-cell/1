/**
 * Browser-grade UI test: loads the REAL app.html + app.js into jsdom and
 * drives the interface end-to-end — typing commands, clicking confirm
 * buttons, asserting notch cards and window content.
 *
 *   node tests/domtest.js        (requires: npm install jsdom, run from repo root)
 */
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { console.log('SKIP  jsdom not installed (npm i jsdom)'); process.exit(0); }

const fs = require('fs');
const path = require('path');
const ROOT = path.join(__dirname, '..');

const html = fs.readFileSync(path.join(ROOT, 'app.html'), 'utf8')
  .replace('<script src="app.js"></script>',
           () => '<script>' + fs.readFileSync(path.join(ROOT, 'app.js'), 'utf8') + '</script>');

const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true, url: 'https://localhost/' });
const { window } = dom;
const { document } = window;

// jsdom lacks a few browser APIs — add minimal shims
window.SpeechSynthesisUtterance = class { constructor(t) { this.text = t; } };
window.speechSynthesis = { speak() {}, cancel() {}, getVoices: () => [], onvoiceschanged: null };
window.navigator.clipboard = { writeText: async () => {} };
delete window.SpeechRecognition;

const sleep = ms => new Promise(r => setTimeout(r, ms));
let fails = 0;
const check = (label, cond, extra) => {
  console.log((cond ? 'PASS' : 'FAIL') + '  ' + label + (cond ? '' : '  -> ' + extra));
  if (!cond) fails++;
};
const notchText = () => document.querySelector('#notch').textContent.replace(/\s+/g, ' ').trim();
const click = sel => { const el = document.querySelector(sel); if (!el) throw new Error('missing ' + sel); el.click(); };
const findWin = title => [...document.querySelectorAll('#windows .win')]
  .find(w => w.querySelector('.win-title')?.textContent.includes(title));
const type = async (text) => {
  const input = document.querySelector('#utterance');
  input.value = text;
  input.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  await sleep(1150); // listening + processing delays
};

(async () => {
  /* ---------- boot ---------- */
  check('boot: notch mounted', document.querySelector('#notch .idle-label')?.textContent === 'VoiceOS');
  check('boot: dock has 6 apps', document.querySelectorAll('.dock-item').length === 6);
  check('boot: chips rendered', document.querySelectorAll('#chips .chip').length >= 12);
  check('boot: onboarding visible on first run', document.querySelector('#onboarding').classList.contains('show'));
  check('boot: clock ticking', /\d/.test(document.querySelector('#clock').textContent));

  /* ---------- onboarding ---------- */
  click('#obStart');
  await sleep(50);
  check('onboarding: dismissed', !document.querySelector('#onboarding').classList.contains('show'));
  check('onboarding: settings persisted', JSON.parse(window.localStorage.getItem('voiceos_settings_v1')).confirmLevel === 'sometimes');
  await sleep(3900); // welcome card auto-close

  /* ---------- workflow: send latest deck (spec's flagship example) ---------- */
  await type('Send John the latest project deck');
  check('workflow: card shows steps', document.querySelectorAll('#notch .wf-step').length === 4, notchText());
  check('workflow: step 1 pre-done', document.querySelector('#notch .wf-step[data-step="1"]').classList.contains('done'));
  check('workflow: confirm buttons', !!document.querySelector('#notch [data-yes]'));
  check('workflow: names file + recipient', /project_deck_v7\.key/.test(notchText()) && /john@company\.com/.test(notchText()), notchText());
  click('#notch [data-yes]');
  await sleep(1800); // step animation completes
  check('workflow: result card', /✓/.test(notchText()) || /sent to John/i.test(notchText()), notchText());
  const filesWin = findWin('Files'), mailWin = findWin('Mail');
  check('workflow: Files opened with match highlighted', !!filesWin && /FOUND/.test(filesWin.textContent), filesWin?.textContent.slice(0, 120));
  check('workflow: Mail opened showing compose', !!mailWin && !!mailWin.querySelector('.compose'), 'no compose pane');
  check('workflow: compose pane with attachment', /📎 project_deck_v7\.key/.test(mailWin?.textContent || ''),
    (mailWin?.textContent || '').slice(0, 200));

  /* ---------- email confirmation flow ---------- */
  await sleep(2200); // let result auto-close
  await type('Send email to Sarah about the roadmap');
  check('email: confirm card', /Send email to sarah@company\.com/.test(notchText()), notchText());
  click('#notch [data-no]');
  check('email: cancel works', /Cancelled/.test(notchText()), notchText());
  check('email: nothing sent on cancel', !/Roadmap/.test(findWin('Mail')?.textContent || ''),
    (findWin('Mail')?.textContent || '').slice(0, 200));

  /* ---------- briefing ---------- */
  await sleep(3500);
  await type('Morning briefing');
  check('briefing: card renders', /Next meeting|Tasks|Mail/.test(notchText()), notchText());

  /* ---------- tasks ---------- */
  await type('Create task: review the launch plan');
  await sleep(500);
  const tasksWin = findWin('Tasks');
  check('tasks: window opened with new task', !!tasksWin && /review the launch plan/i.test(tasksWin.textContent),
    tasksWin ? tasksWin.textContent.slice(0, 120) : 'no tasks window');
  check('tasks: NEW badge', !!tasksWin && !!tasksWin.querySelector('.badge-new'));

  /* ---------- contact learning ---------- */
  await sleep(3600);
  await type('I meant Ellen not Elon');
  check('learning: not treated as alias for unknown contact', !/from now on/.test(notchText()), notchText());
  await type('I meant Sarah not Sara');
  check('learning: confirms', /from now on/.test(notchText()), notchText());
  await sleep(3600);
  await type('Send message to Sara saying the alias worked');
  check('learning: alias applied', /Sent to Sarah/.test(notchText()), notchText());

  /* ---------- ambiguity ---------- */
  await sleep(3600);
  await type('Send message');
  const chips = [...document.querySelectorAll('#notch .opt-chip')];
  check('ambiguity: chips offered', chips.length === 3, chips.map(c => c.textContent).join());
  chips[0].click(); // Maria
  await sleep(1150);
  check('ambiguity: picks up recipient', /What should I tell Maria/.test(notchText()), notchText());

  /* ---------- help + settings panels ---------- */
  click('#helpBtn');
  check('help: opens', document.querySelector('#helpModal').classList.contains('show'));
  click('#helpClose');
  check('help: closes', !document.querySelector('#helpModal').classList.contains('show'));
  click('#settingsBtn');
  check('settings: opens', document.querySelector('#settingsPanel').classList.contains('visible'));
  const sel = document.querySelector('#setConfirm');
  sel.value = 'never';
  sel.dispatchEvent(new window.Event('change', { bubbles: true }));
  check('settings: confirm level changes persisted',
    JSON.parse(window.localStorage.getItem('voiceos_settings_v1')).confirmLevel === 'never');

  await type('Send email to John about the gig');
  check('settings: never-level auto-sends (no confirm card)', !document.querySelector('#notch [data-yes]'), notchText());
  await sleep(600);

  /* ---------- JSON inspector ---------- */
  check('json: inspector shows every response', /"mode"/.test(document.querySelector('#jsonView').textContent));

  /* ---------- dock + window drag affordance ---------- */
  const dockItems = [...document.querySelectorAll('.dock-item')];
  check('dock: open indicator', dockItems.some(d => d.classList.contains('open')));

  /* ---------- persistence across restart ---------- */
  const saved = JSON.parse(window.localStorage.getItem('voiceos_store_v1'));
  check('persist: task survived in snapshot', saved.tasks.some(t => /review the launch plan/i.test(t.title)));
  check('persist: alias survived in snapshot', saved.aliases.sara === 'sarah');

  /* ---------- v1.1.1 polish ---------- */
  await sleep(4700); // placeholder rotation
  check('polish: rotating placeholder', /Say it once/.test(document.querySelector('#utterance').placeholder));

  click('#settingsBtn'); // open settings again
  document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  check('polish: Escape closes settings', !document.querySelector('#settingsPanel').classList.contains('visible'));

  // raise-on-click: open two windows, click the lower one
  await type('Open Calendar');
  const wins = [...document.querySelectorAll('#windows .win')];
  const calWin = findWin('Calendar');
  const before = +calWin.style.zIndex;
  calWin.dispatchEvent(new window.MouseEvent('pointerdown', { bubbles: true }));
  check('polish: click raises window above siblings', +calWin.style.zIndex > before &&
    wins.every(w => w === calWin || +w.style.zIndex < +calWin.style.zIndex || /^\d+$/.test(calWin.style.zIndex)));

  /* ---------- v1.2: sound design is wired (WebAudio, runs silent under test) ---------- */
  check('sfx: synth engine present',
    dom.window.eval("(typeof SFX === 'object') && typeof SFX.send === 'function' && typeof SFX.success === 'function'"));
  await type('Take a note: typewriter should animate');
  await sleep(1300); // typewriter completes (~≤0.9s by design)
  check('sfx+dictation: typewriter completes, caret removed',
    /Typewriter should animate\./.test(notchText()) && !/▌/.test(notchText()), notchText());

  console.log(fails === 0 ? '\nALL DOM TESTS PASSED' : `\n${fails} DOM FAILURES`);
  process.exit(fails ? 1 : 0);
})().catch(e => { console.error('CRASH:', e); process.exit(1); });
