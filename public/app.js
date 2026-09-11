/* JARVIS dashboard — vanilla JS, talks to the daemon's REST + SSE API. */
const $ = (sel) => document.querySelector(sel);
const core = $('#core');
let conversationId = null;
let speakReplies = false;

/* ── tabs ── */
document.querySelectorAll('.nav').forEach((btn) => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav').forEach((b) => b.classList.remove('active'));
    document.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
    btn.classList.add('active');
    $(`#tab-${btn.dataset.tab}`).classList.add('active');
  });
});

/* ── toasts ── */
function toast(text, ms = 6000) {
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = text;
  $('#toasts').appendChild(el);
  setTimeout(() => el.remove(), ms);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'content-type': 'application/json' },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  return res.json();
}

/* ── chat ── */
const messages = $('#messages');

function addMsg(role, text, agent) {
  const el = document.createElement('div');
  el.className = `msg ${role}`;
  const who = document.createElement('div');
  who.className = 'who';
  who.textContent = role === 'user' ? 'you' : agent && agent !== 'orchestrator' ? `jarvis · ${agent}` : 'jarvis';
  el.appendChild(who);
  const body = document.createElement('span');
  body.textContent = text;
  el.appendChild(body);
  messages.appendChild(el);
  messages.scrollTop = messages.scrollHeight;
  return body;
}

function addToolNote(tool) {
  const el = document.createElement('div');
  el.className = 'msg assistant';
  el.innerHTML = `<span class="tool">🔧 using tool: <b></b></span>`;
  el.querySelector('b').textContent = tool;
  messages.appendChild(el);
  messages.scrollTop = messages.scrollHeight;
  return el;
}

async function sendChat(text) {
  if (!text.trim()) return;
  addMsg('user', text);
  $('#chat-input').value = '';
  core.classList.add('busy');
  const body = addMsg('assistant', '');
  body.textContent = '…';
  let full = '';
  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ message: text, conversation_id: conversationId, stream: true }),
    });
    if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let first = true;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        const dataLine = block.split('\n').find((l) => l.startsWith('data: '));
        if (!dataLine) continue;
        let data;
        try { data = JSON.parse(dataLine.slice(6)); } catch { continue; }
        if (block.startsWith('event: token')) {
          if (first) { body.textContent = ''; first = false; }
          full += data.delta ?? '';
          body.textContent = full;
          messages.scrollTop = messages.scrollHeight;
        } else if (block.startsWith('event: done')) {
          conversationId = data.conversation_id;
          $('#conv-label').textContent = `conversation #${conversationId}`;
          if (!full && data.answer) body.textContent = data.answer;
          if (speakReplies) speak(data.answer || full);
        } else if (block.startsWith('event: error')) {
          body.textContent = `⚠ ${data.message}`;
        }
      }
    }
  } catch (err) {
    body.textContent = `⚠ ${err.message}`;
  } finally {
    core.classList.remove('busy');
  }
}

$('#chat-form').addEventListener('submit', (e) => {
  e.preventDefault();
  sendChat($('#chat-input').value);
});
$('#new-chat').addEventListener('click', () => {
  conversationId = null;
  messages.innerHTML = '';
  $('#conv-label').textContent = 'new conversation';
});

/* ── voice (browser Web Speech API — free, no keys) ── */
function speak(text) {
  if (!('speechSynthesis' in window) || !text) return;
  const u = new SpeechSynthesisUtterance(text.replace(/[#*_`]/g, '').slice(0, 600));
  u.rate = 1.05;
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
}

$('#speak-toggle').addEventListener('click', (e) => {
  speakReplies = !speakReplies;
  e.currentTarget.classList.toggle('off', !speakReplies);
  toast(speakReplies ? 'Spoken replies ON' : 'Spoken replies OFF', 2000);
});

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
if (SR) {
  const rec = new SR();
  rec.lang = navigator.language || 'en-US';
  rec.interimResults = false;
  rec.onresult = (e) => {
    const text = e.results[0][0].transcript;
    $('#mic').classList.remove('listening');
    sendChat(text);
  };
  rec.onerror = () => $('#mic').classList.remove('listening');
  rec.onend = () => $('#mic').classList.remove('listening');
  $('#mic').addEventListener('click', () => {
    $('#mic').classList.add('listening');
    try { rec.start(); } catch { /* already started */ }
  });
} else {
  $('#mic').style.display = 'none';
}

/* ── memory ── */
async function loadMemories() {
  const q = $('#memory-search').value.trim();
  const data = await api(`/api/memories${q ? `?q=${encodeURIComponent(q)}` : ''}`);
  const list = $('#memory-list');
  list.innerHTML = '';
  for (const m of data.memories) {
    const li = document.createElement('li');
    const actions = document.createElement('span');
    actions.className = 'actions';
    const del = document.createElement('button');
    del.textContent = '✕';
    del.onclick = async () => { await api(`/api/memories/${m.id}`, { method: 'DELETE' }); loadMemories(); };
    actions.appendChild(del);
    li.appendChild(actions);
    const badge = document.createElement('span');
    badge.className = 'badge';
    badge.textContent = m.kind;
    li.appendChild(badge);
    li.appendChild(document.createTextNode(`${m.title} `));
    if (m.body) {
      const body = document.createElement('div');
      body.className = 'small';
      body.textContent = m.body;
      li.appendChild(body);
    }
    const meta = document.createElement('div');
    meta.className = 'small';
    meta.textContent = `${m.created_at}${m.tags ? ` · ${m.tags}` : ''}`;
    li.appendChild(meta);
    list.appendChild(li);
  }
  if (!data.memories.length) list.innerHTML = '<li class="small">No memories yet — teach JARVIS something.</li>';
}
$('#memory-refresh').addEventListener('click', loadMemories);
$('#memory-search').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); loadMemories(); } });
$('#memory-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  await api('/api/memories', {
    method: 'POST',
    body: { title: $('#memory-title').value, body: $('#memory-body').value, kind: $('#memory-kind').value },
  });
  $('#memory-title').value = '';
  $('#memory-body').value = '';
  loadMemories();
});

/* ── goals ── */
async function loadGoals() {
  const data = await api('/api/goals');
  const list = $('#goal-list');
  list.innerHTML = '';
  for (const g of data.goals) {
    const li = document.createElement('li');
    const actions = document.createElement('span');
    actions.className = 'actions';
    for (const [label, status] of [['✓ done', 'done'], ['drop', 'dropped'], ['reopen', 'open']]) {
      if (status === g.status) continue;
      const b = document.createElement('button');
      b.textContent = label;
      b.onclick = async () => { await api(`/api/goals/${g.id}`, { method: 'PATCH', body: { status } }); loadGoals(); };
      actions.appendChild(b);
    }
    li.appendChild(actions);
    const title = document.createElement('b');
    title.textContent = `#${g.id} ${g.title}`;
    li.appendChild(title);
    if (g.status !== 'open') {
      const st = document.createElement('span');
      st.className = 'badge';
      st.textContent = g.status;
      li.appendChild(st);
    }
    if (g.deadline) {
      const dl = document.createElement('span');
      dl.className = 'small';
      dl.textContent = ` · deadline ${g.deadline}`;
      li.appendChild(dl);
    }
    for (const kr of g.key_results || []) {
      const k = document.createElement('div');
      k.className = `kr ${kr.status === 'done' ? 'done' : ''}`;
      k.textContent = `${kr.status === 'done' ? '✓' : '○'} ${kr.title} (${kr.current}/${kr.target})`;
      if (kr.status !== 'done') {
        const plus = document.createElement('button');
        plus.textContent = '+';
        plus.style.marginLeft = '8px';
        plus.onclick = async () => { await api(`/api/key-results/${kr.id}/advance`, { method: 'POST', body: { delta: 1 } }); loadGoals(); };
        k.appendChild(plus);
      }
      li.appendChild(k);
    }
    list.appendChild(li);
  }
  if (!data.goals.length) list.innerHTML = '<li class="small">No open goals. Create one, or ask JARVIS to plan something.</li>';
}
$('#goal-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  await api('/api/goals', {
    method: 'POST',
    body: {
      title: $('#goal-title').value,
      deadline: $('#goal-deadline').value || undefined,
      key_results: $('#goal-krs').value.split(',').map((s) => s.trim()).filter(Boolean),
    },
  });
  $('#goal-title').value = '';
  $('#goal-krs').value = '';
  $('#goal-deadline').value = '';
  loadGoals();
});

/* ── system ── */
async function loadHealth() {
  try {
    const h = await api('/api/health');
    $('#health').textContent = JSON.stringify(h, null, 2);
    const pill = $('#status-pill');
    if (h.ollama.reachable) {
      pill.textContent = `online · ${h.model}`;
      pill.className = 'ok';
    } else {
      pill.textContent = 'ollama unreachable';
      pill.className = 'bad';
    }
    if (!$('#authority').matches(':active')) $('#authority').value = h.authority;
    $('#auth-value').textContent = h.authority;
  } catch {
    const pill = $('#status-pill');
    pill.textContent = 'daemon offline';
    pill.className = 'bad';
  }
}

async function loadModels() {
  try {
    const data = await api('/api/models');
    const el = $('#models');
    el.innerHTML = '';
    if (data.error) { el.textContent = data.error; return; }
    for (const m of data.installed) {
      const d = document.createElement('div');
      d.className = 'model';
      const configured = m.name === data.configured.model || m.name === data.configured.fast_model;
      d.textContent = `${m.name} — ${m.size_gb} GB${configured ? ' ★ configured' : ''}`;
      el.appendChild(d);
    }
    if (!data.installed.length) el.textContent = 'No models installed yet — pull one below.';
  } catch (err) {
    $('#models').textContent = String(err);
  }
}

$('#btn-pull').addEventListener('click', async () => {
  const model = $('#pull-model').value.trim();
  if (!model) return;
  await api('/api/models/pull', { method: 'POST', body: { model } });
  toast(`Pulling ${model}… watch the event feed`);
});

$('#authority').addEventListener('change', async (e) => {
  const data = await api('/api/authority', { method: 'PATCH', body: { level: Number(e.target.value) } });
  $('#auth-value').textContent = data.level;
  toast(`Authority level set to ${data.level}`);
});

for (const [btn, route, key] of [
  ['#btn-morning', '/api/routines/morning', 'plan'],
  ['#btn-evening', '/api/routines/evening', 'review'],
]) {
  $(btn).addEventListener('click', async () => {
    $(btn).disabled = true;
    $('#routine-out').textContent = 'thinking…';
    const data = await api(route, { method: 'POST' });
    $('#routine-out').textContent = data[key] ?? data.error ?? JSON.stringify(data);
    $(btn).disabled = false;
  });
}
$('#btn-heartbeat').addEventListener('click', async () => {
  const data = await api('/api/routines/heartbeat', { method: 'POST' });
  $('#routine-out').textContent = JSON.stringify(data.alerts, null, 2);
});

/* ── live event feed ── */
const evtList = $('#events');
function feedEvent(evt) {
  const li = document.createElement('li');
  const ts = document.createElement('span');
  ts.className = 'ts';
  ts.textContent = evt.ts.slice(11, 19);
  li.appendChild(ts);
  li.appendChild(document.createTextNode(` ${evt.type} `));
  const payload = document.createElement('span');
  payload.className = 'ts';
  const text = JSON.stringify(evt.payload ?? {});
  payload.textContent = text.length > 160 ? `${text.slice(0, 160)}…` : text;
  li.appendChild(payload);
  evtList.prepend(li);
  while (evtList.children.length > 120) evtList.lastChild.remove();
}

function connectEvents() {
  const es = new EventSource('/api/events/stream');
  es.addEventListener('event', (e) => {
    const evt = JSON.parse(e.data);
    feedEvent(evt);
    if (evt.type === 'notify') toast(evt.payload.message);
    if (evt.type === 'agent:tool') addToolNote(evt.payload.tool);
    if (evt.type === 'goal:deadline') {
      toast(`⏰ Goal "${evt.payload.title}" ${evt.payload.overdue ? 'is OVERDUE' : `due in ${evt.payload.days_left}d`}`);
    }
    if (evt.type === 'pull:done') { toast(`✅ Model ${evt.payload.model} ready`); loadModels(); }
    if (evt.type === 'pull:error') toast(`❌ Pull failed: ${evt.payload.error}`);
  });
  es.onerror = () => { es.close(); setTimeout(connectEvents, 3000); };
}

/* ── boot ── */
loadHealth();
loadModels();
loadMemories();
loadGoals();
connectEvents();
setInterval(loadHealth, 8000);
