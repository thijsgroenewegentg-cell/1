/* Landing page: looping "specimen" demo in the hero card. */
(function () {
  const scenes = [
    {
      tag: 'Agent mode · confirmation',
      title: 'Send email to John about the meeting',
      lines: [['To', 'john@company.com'], ['Subject', 'The Meeting']],
      actions: ['SEND', 'CANCEL'],
    },
    {
      tag: 'Workflow · 4 steps',
      title: 'Send John the latest project deck',
      lines: [['✓ Found', 'project_deck_v7.key'], ['◐ Compose', 'john@company.com'], ['○ Attach', 'waiting'], ['○ Send', 'waiting']],
      actions: ['RUN', 'CANCEL'],
    },
    {
      tag: 'Dictation mode',
      title: '“um so the onboarding uh tested well”',
      lines: [['Cleaned', 'The onboarding tested well.'], ['Typed into', 'Notes']],
      actions: ['DONE'],
    },
    {
      tag: 'Morning briefing',
      title: 'Your day at a glance',
      lines: [['Meeting', 'Design review · 2:00 PM'], ['Mail', '1 unread — Maya'], ['Tasks', '2 open']],
      actions: ['OK'],
    },
  ];

  const el = id => document.getElementById(id);
  const tagEl = el('demoTag'), titleEl = el('demoTitle'),
        linesEl = el('demoLines'), actionsEl = el('demoActions');
  if (!tagEl) return;

  const sleep = ms => new Promise(r => setTimeout(r, ms));

  async function typeTitle(text) {
    titleEl.innerHTML = '<span class="caret"></span>';
    for (let i = 0; i <= text.length; i++) {
      titleEl.innerHTML = text.slice(0, i).replace(/</g, '&lt;') + '<span class="caret"></span>';
      await sleep(34);
    }
    titleEl.innerHTML = text.replace(/</g, '&lt;');
  }

  async function play(scene) {
    tagEl.textContent = scene.tag;
    linesEl.innerHTML = '';
    actionsEl.innerHTML = '';
    await typeTitle(scene.title);
    for (const [k, v] of scene.lines) {
      const dk = document.createElement('span'); dk.className = 'k'; dk.textContent = k;
      const dv = document.createElement('span'); dv.className = 'v'; dv.textContent = v;
      linesEl.append(dk, dv);
      await sleep(240);
    }
    for (const a of scene.actions) {
      const b = document.createElement('span');
      b.className = 'demo-btn' + (a === 'SEND' || a === 'RUN' ? ' primary' : '');
      b.textContent = a;
      actionsEl.appendChild(b);
    }
    await sleep(2600);
  }

  (async function loop() {
    let i = 0;
    for (;;) { await play(scenes[i % scenes.length]); i++; await sleep(900); }
  })();
})();
