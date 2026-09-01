// Node smoke test: stub the browser surface, eval app.js, drive parse() and
// the full handleUtterance() pipeline (headless) against the spec's examples.
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');

const dummyEl = () => ({
  innerHTML: '', textContent: '', className: '', value: '', style: {}, dataset: {},
  classList: { add() {}, remove() {}, toggle() {} },
  addEventListener() {}, appendChild() {}, prepend() {}, remove() {}, focus() {},
  querySelector: () => dummyEl(), querySelectorAll: () => [],
  getBoundingClientRect: () => ({ left: 0, top: 0, width: 1200, height: 800 }),
  scrollTop: 0, scrollHeight: 0, lastChild: null, children: [],
});

global.document = {
  querySelector: () => dummyEl(),
  querySelectorAll: () => [],
  createElement: () => dummyEl(),
  addEventListener() {},
};
global.window = { addEventListener() {} }; // no SpeechRecognition / speechSynthesis

const tests = `
;(async function runTests(){
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  let fails = 0;
  const check = (label, cond, extra) => {
    console.log((cond ? 'PASS' : 'FAIL') + '  ' + label + (cond ? '' : '  -> ' + JSON.stringify(extra)));
    if (!cond) fails++;
  };

  /* ---------- unit: parse() intent coverage ---------- */

  let r = parse('Send email to John about the meeting');
  check('email: action', r.action === 'send_email', r);
  check('email: needs confirmation', r.requires_confirmation === true);
  check('email: recipient resolved', r.parameters.to === 'john@company.com', r.parameters);
  check('email: subject extracted', r.parameters.subject === 'The Meeting', r.parameters);
  check('email: spoken response <15 words', r.response.split(' ').length < 15, r.response);

  // simulate the pending-confirmation wiring handleUtterance() performs
  state.pending = { type: 'confirm', resp: r, onConfirm: () => {
    state.pending = null; const x = exec(r);
    return makeResponse({ ...r, result: x.result, _handled: true });
  }};
  const r2 = parse('yes');
  check('email: voice "yes" confirms', r2._handled === true, r2);
  check('email: actually sent', r2.result === 'Email sent to John' && store.sent.length === 1, { result: r2.result, sent: store.sent.length });

  r = parse('Schedule meeting with Sarah next week');
  check('schedule: action+attendee', r.action === 'schedule_meeting' && r.parameters.attendee === 'sarah@company.com', r);
  check('schedule: needs confirmation', r.requires_confirmation === true);
  state.pending = null;

  r = parse('Find last year’s tax returns'); // curly apostrophe, as the chip sends
  check('files: search mode', r.mode === 'search' && (r.action === 'find_file' || r.action === 'open_file'), r);
  check('files: 3 tax matches', r.card_data.results.length === 3, r.card_data.results);

  r = parse('Reply to Maya');
  check('reply: collects body', state.pending && state.pending.field === 'body', state.pending);
  r = parse('Running ten minutes late, see you there');
  check('reply: sends without confirmation', r.action === 'reply_message' && !r.requires_confirmation, r);
  exec(r); // execution layer performs the side effect
  check('reply: appended to thread', store.threads.maya.slice(-1)[0].text.includes('Running ten'), store.threads.maya.slice(-1));

  r = parse('Send message');
  check('ambig: asks who with options', /To who/.test(r.response) && r.options.length === 3, r.response);
  r = parse('Maria');
  check('ambig: recipient filled', r.action === 'send_message' || (state.pending && state.pending.params.contact.name === 'Maria'), r);
  r = parse('Lunch on Thursday works for me');
  check('ambig: sends follow-up', r.action === 'send_message' && r.parameters.to === 'Maria', r);

  r = parse('Take a note: um the new onboarding flow uh tested well');
  check('dictation: mode+action', r.mode === 'dictation' && r.action === 'create_note', r);
  check('dictation: fillers removed, punctuated', r.parameters.content === 'The new onboarding flow tested well.', r.parameters.content);

  r = parse('What’s my next meeting?');
  check('next meeting', r.action === 'find_next_meeting', r);

  r = parse('Check availability for Sarah');
  check('availability: contact', r.action === 'check_availability' && r.parameters.person === 'sarah@company.com', r);
  r = parse('Is Alex free friday?');
  check('availability: alt phrasing', r.action === 'check_availability' && r.parameters.person === 'alex@company.com', r);

  r = parse('Remind me to call Joan tomorrow at 9am');
  check('reminder: action', r.action === 'create_reminder', r);
  check('reminder: clean task', r.parameters.task === 'call joan', r.parameters);
  check('reminder: parsed 9am', new Date(r.parameters.when).getHours() === 9, r.parameters.when);

  r = parse('Open Notes');
  check('open app', r.action === 'open_app' && r.parameters.app === 'Notes', r);

  r = parse('Search web for focus timing');
  check('web search', r.action === 'search_web', r);

  r = parse('Send my password to Alex');
  check('safety: password refused', !r.action && /manually/i.test(r.response), r.response);
  r = parse('Delete all my emails');
  check('safety: mass-delete refused', /risky/i.test(r.response), r.response);

  r = parse('blorp fizzle womp');
  check('unclear fallback', r.mode === 'unclear' && r.confidence < 0.6, r);

  /* ---------- v1.0: confirmation levels (spec: always/sometimes/never) ---------- */
  check('confirm: matrix sometimes', shouldConfirm('send_email') === true && shouldConfirm('send_message') === false);
  settings.confirmLevel = 'never';
  check('confirm: never → email auto-sends', shouldConfirm('send_email') === false);
  r = parse('Send email to John about the roadmap');
  check('confirm: never removes card', r.requires_confirmation === false, r);
  settings.confirmLevel = 'always';
  check('confirm: always → messages ask', shouldConfirm('send_message') === true);
  r = parse('Send message to Alex saying I am in');
  check('confirm: always adds message card', r.requires_confirmation === true && /Confirm/.test(r.response), r);
  settings.confirmLevel = 'sometimes';

  /* ---------- v1.0: persistence round trip ---------- */
  const mem = {};
  global.localStorage = {
    getItem: k => (k in mem ? mem[k] : null),
    setItem: (k, v) => { mem[k] = String(v); },
    removeItem: k => { delete mem[k]; },
  };
  store.notes.push({ text: 'persistence-probe note', fresh: false });
  store.events.push({ title: 'Probe event', when: at(5, 10, 0), who: [], fresh: false });
  persist();
  store.notes = []; store.events = [];
  loadPersisted();
  check('persist: notes restored', store.notes.some(n => n.text === 'persistence-probe note'), store.notes);
  check('persist: event dates revived', store.events.some(e => e.title === 'Probe event' && e.when instanceof Date),
    store.events.map(e => e.title + ':' + (e.when instanceof Date)));
  store.notes = store.notes.filter(n => n.text !== 'persistence-probe note');
  store.events = store.events.filter(e => e.title !== 'Probe event');
  delete global.localStorage;

  /* ---------- v1.1: contact learning (spec: "Actually, I meant Sarah not Sara") ---------- */
  state.aliases = {}; // isolate from localStorage persistence
  r = parse('I meant Sarah not Sara');
  check('learn: correction action', r.action === 'learn_alias' && /Sarah/.test(r.response), r);
  check('learn: alias stored', state.aliases.sara === 'sarah', state.aliases);
  check('learn: alias resolves', findContact(' sara ').email === 'sarah@company.com', findContact(' sara '));
  r = parse('Send message to Sara saying learned');
  check('learn: applies to future commands', r.action === 'send_message' && r.parameters.to === 'Sarah', r);

  /* ---------- v1.1: multi-step workflow (spec example verbatim) ---------- */
  r = parse('Send John the latest project deck');
  check('workflow: action', r.action === 'send_file_workflow', r);
  check('workflow: steps', Array.isArray(r.workflow_steps) && r.workflow_steps.length === 4, r.workflow_steps);
  check('workflow: step1 found', r.workflow_steps[0].state === 'done' && /project_deck_v7/.test(r.workflow_steps[0].label), r.workflow_steps[0]);
  check('workflow: confirms at step 2', r.requires_confirmation === true && r.confirmation_at_step === 2, r);
  check('workflow: file resolved', r.parameters.file === 'project_deck_v7.key', r.parameters);
  const execOut = exec(r);
  check('workflow: exec attaches + sends', /project_deck_v7\.key sent to John/.test(execOut.result), execOut);
  check('workflow: lands in Sent with attachment', store.sent[0].body.includes('📎 project_deck_v7.key'), store.sent[0].body);

  /* ---------- v1.1: morning briefing ---------- */
  r = parse('Morning briefing');
  check('briefing: action', r.action === 'daily_briefing', r);
  check('briefing: card with lines', r.card_type === 'briefing' && r.card_data.lines.length >= 3, r.card_data);
  check('briefing: spoken summary short', r.response.split(' ').length < 20, r.response);
  r = parse('Start my day');
  check('briefing: alt phrasing', r.action === 'daily_briefing', r);

  /* ---------- v1.1: tasks ---------- */
  r = parse('Create task: review the launch plan');
  check('task: action+title', r.action === 'create_task' && /review/i.test(r.parameters.title), r);
  exec(r);
  check('task: stored', store.tasks.some(x => /review the launch plan/i.test(x.title)), store.tasks);
  r = parse("Show my tasks");
  check('task: list', r.action === 'list_tasks' && r.card_type === 'search_result', r);
  check('task: list has resultApp', r.card_data.resultApp === 'Tasks', r.card_data);

  /* ---------- v1.1: notes search ---------- */
  r = parse('Search notes for checklist');
  check('notes: search', r.action === 'search_notes' && r.card_data.results.length === 1, r);
  check('notes: resultApp', r.card_data.resultApp === 'Notes', r.card_data);

  /* ---------- safety: workflow with confirmation level never ---------- */
  settings.confirmLevel = 'never';
  r = parse('Send John the latest project deck');
  check('workflow: never-level auto-runs', r.requires_confirmation === false, r);
  settings.confirmLevel = 'sometimes';

  /* ---------- integration: full headless pipeline ---------- */
  let threw = null;
  try {
    handleUtterance('Schedule meeting with Sarah next week'); await sleep(1150);
    check('pipeline: confirm pending', state.pending && state.pending.type === 'confirm', state.pending);
    handleUtterance('yes'); await sleep(1150);
    check('pipeline: event booked', store.events.some(e => e.title === 'Meeting with Sarah'), store.events.map(e => e.title));
    handleUtterance('Find last year’s tax returns'); await sleep(1150);
    handleUtterance('Take a note: ship it friday'); await sleep(1150);
    check('pipeline: note stored', store.notes.some(n => /Ship it friday/.test(n.text)), store.notes);
  } catch (e) { threw = e; }
  check('pipeline: no exceptions end-to-end', threw === null, threw && threw.stack);

  console.log(fails === 0 ? '\\nALL TESTS PASSED' : '\\n' + fails + ' FAILURES');
  process.exit(fails ? 1 : 0);
})();
`;

eval(src + tests);
