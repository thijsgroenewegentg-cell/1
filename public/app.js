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

/* ── voice: server-side (piper/whisper) with browser fallback ── */
let voiceStatus = null;

async function loadVoiceStatus() {
  try {
    voiceStatus = await api('/api/voice/config');
    const el = $('#voice-status');
    if (el) {
      el.innerHTML =
        `TTS: <b>${voiceStatus.tts.detail}</b> · STT: <b>${voiceStatus.stt.detail}</b>`;
    }
  } catch { voiceStatus = null; }
}

async function speak(text) {
  if (!text) return;
  const clean = text.replace(/[#*_`]/g, '').slice(0, 600);
  if (voiceStatus && voiceStatus.tts.available) {
    try {
      const res = await fetch('/api/tts', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text: clean }),
      });
      if (res.ok) {
        const buf = await res.arrayBuffer();
        const audio = new Audio(URL.createObjectURL(new Blob([buf], { type: 'audio/wav' })));
        audio.play();
        return;
      }
    } catch { /* fall through to browser TTS */ }
  }
  if (!('speechSynthesis' in window)) return;
  const u = new SpeechSynthesisUtterance(clean);
  u.rate = 1.05;
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
}

/** Record the mic and transcribe via server whisper (with browser fallback). */
async function recordAndTranscribe(onText) {
  if (!(voiceStatus && voiceStatus.stt.available)) return false; // caller falls back
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const rec = new MediaRecorder(stream);
    const chunks = [];
    rec.ondataavailable = (e) => chunks.push(e.data);
    rec.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      try {
        const blob = new Blob(chunks, { type: rec.mimeType || 'audio/webm' });
        const wav = await audioBlobToWav16k(blob);
        const res = await fetch('/api/stt', { method: 'POST', body: wav });
        if (res.ok) {
          const data = await res.json();
          if (data.text) onText(data.text);
          else toast('Heard nothing — try again closer to the mic.');
        } else {
          toast('Server STT failed — check whisper config.');
        }
      } catch (err) { toast(`STT error: ${err.message}`); }
    };
    rec.start();
    setTimeout(() => rec.state !== 'inactive' && rec.stop(), 20000); // max 20s
    return true;
  } catch { return false; }
}

/** Decode any browser audio blob → 16 kHz mono 16-bit WAV (for whisper.cpp). */
async function audioBlobToWav16k(blob) {
  const arr = await blob.arrayBuffer();
  const ac = new AudioContext();
  const decoded = await ac.decodeAudioData(arr);
  const rate = 16000;
  const off = new OfflineAudioContext(1, Math.ceil(decoded.duration * rate), rate);
  const src = off.createBufferSource();
  src.buffer = decoded;
  src.connect(off.destination);
  src.start();
  const rendered = await off.startRendering();
  await ac.close();
  const samples = rendered.getChannelData(0);
  const pcm = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  const header = new DataView(new ArrayBuffer(44));
  const writeStr = (o, s) => { for (let i = 0; i < s.length; i++) header.setUint8(o + i, s.charCodeAt(i)); };
  writeStr(0, 'RIFF'); header.setUint32(4, 36 + pcm.byteLength, true); writeStr(8, 'WAVE');
  writeStr(12, 'fmt '); header.setUint32(16, 16, true); header.setUint16(20, 1, true);
  header.setUint16(22, 1, true); header.setUint32(24, rate, true);
  header.setUint32(28, rate * 2, true); header.setUint16(32, 2, true); header.setUint16(34, 16, true);
  writeStr(36, 'data'); header.setUint32(40, pcm.byteLength, true);
  return new Blob([header.buffer, pcm.buffer], { type: 'audio/wav' });
}

$('#speak-toggle').addEventListener('click', (e) => {
  speakReplies = !speakReplies;
  e.currentTarget.classList.toggle('off', !speakReplies);
  toast(speakReplies ? 'Spoken replies ON' : 'Spoken replies OFF', 2000);
});

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let listening = false;

async function startListening() {
  if (listening) return;
  listening = true;
  $('#mic').classList.add('listening');
  const finish = (text) => {
    listening = false;
    $('#mic').classList.remove('listening');
    if (text) sendChat(text);
  };
  // preferred: record → server whisper
  const usedServer = await recordAndTranscribe(finish);
  if (usedServer) return;
  // fallback: browser SpeechRecognition
  if (SR) {
    const rec = new SR();
    rec.lang = navigator.language || 'en-US';
    rec.interimResults = false;
    rec.onresult = (e) => finish(e.results[0][0].transcript);
    rec.onerror = () => finish(null);
    rec.onend = () => finish(null);
    try { rec.start(); } catch { finish(null); }
  } else {
    finish(null);
    toast('No speech input available (no whisper config, no browser SpeechRecognition).');
  }
}
$('#mic').addEventListener('click', startListening);

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
$('#memory-reindex').addEventListener('click', async () => {
  const data = await api('/api/memories/reindex', { method: 'POST', body: {} });
  toast(`Embedded ${data.embedded ?? 0} memories`);
});
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

/* ── approvals ── */
function approvalButtons(id, compact) {
  const wrap = document.createElement('span');
  wrap.className = 'actions';
  for (const [label, decision, cls] of [['✔ allow', 'approved', 'ok'], ['✖ deny', 'denied', 'bad']]) {
    const b = document.createElement('button');
    b.textContent = label;
    if (!compact) b.classList.add(cls === 'ok' ? 'primary' : 'danger');
    b.onclick = async () => {
      await api(`/api/approvals/${id}`, { method: 'POST', body: { decision } });
      loadApprovals();
    };
    wrap.appendChild(b);
  }
  return wrap;
}

async function loadApprovals() {
  try {
    const data = await api('/api/approvals');
    $('#approval-count').textContent = data.pending.length;
    const list = $('#approval-list');
    list.innerHTML = '';
    for (const a of data.pending) {
      const li = document.createElement('li');
      li.appendChild(approvalButtons(a.id, false));
      const t = document.createElement('b');
      t.textContent = `#${a.id} ${a.tool}`;
      li.appendChild(t);
      const d = document.createElement('div');
      d.className = 'small';
      let args = '';
      try { args = JSON.stringify(JSON.parse(a.args)); } catch { args = a.args; }
      d.textContent = `${a.reason} · args: ${args.slice(0, 160)}`;
      li.appendChild(d);
      list.appendChild(li);
    }
    if (!data.pending.length) list.innerHTML = '<li class="small">Nothing waiting for approval.</li>';
  } catch { /* daemon offline */ }
}

function approvalToast(payload) {
  const el = document.createElement('div');
  el.className = 'toast approval';
  const title = document.createElement('b');
  title.textContent = `🔐 JARVIS needs permission: ${payload.tool}`;
  el.appendChild(title);
  const body = document.createElement('div');
  body.className = 'small';
  body.textContent = payload.reason;
  el.appendChild(body);
  el.appendChild(approvalButtons(payload.id, true));
  $('#toasts').appendChild(el);
  // approval toasts stay until resolved
}

/* ── workflows ── */
async function loadWorkflows() {
  try {
    const data = await api('/api/workflows');
    $('#wf-dir').textContent = `Definitions live in ${data.dir} (*.yaml) — reload after editing.`;
    const list = $('#wf-list');
    list.innerHTML = '';
    for (const w of data.workflows) {
      const li = document.createElement('li');
      const actions = document.createElement('span');
      actions.className = 'actions';
      const run = document.createElement('button');
      run.textContent = '▶ run';
      run.onclick = async () => {
        const r = await api(`/api/workflows/${w.id}/run`, { method: 'POST', body: {} });
        toast(`Workflow "${w.id}" → ${r.status}`);
        loadRuns();
      };
      actions.appendChild(run);
      li.appendChild(actions);
      const t = document.createElement('b');
      t.textContent = `${w.name}${w.enabled ? '' : ' (disabled)'}`;
      li.appendChild(t);
      const meta = document.createElement('div');
      meta.className = 'small';
      meta.textContent = `trigger: ${w.trigger.type}${w.trigger.expr ? ` ${w.trigger.expr}` : ''}${w.trigger.path ? ` ${w.trigger.path}` : ''}${w.trigger.event ? ` ${w.trigger.event}` : ''} · steps: ${w.steps.join(' → ')}`;
      li.appendChild(meta);
      list.appendChild(li);
    }
    if (!data.workflows.length) list.innerHTML = '<li class="small">No workflows yet — drop a .yaml file in the workflows folder (see examples/workflows).</li>';
    loadRuns();
  } catch { /* offline */ }
}

async function loadRuns() {
  try {
    const data = await api('/api/workflows/runs');
    const list = $('#wf-runs');
    list.innerHTML = '';
    for (const r of data.runs) {
      const li = document.createElement('li');
      const badge = document.createElement('span');
      badge.className = `badge ${r.status === 'done' ? 'ok' : r.status === 'failed' ? 'bad' : ''}`;
      badge.textContent = r.status;
      li.appendChild(badge);
      li.appendChild(document.createTextNode(` ${r.workflow} · ${r.started_at}`));
      if (r.log) {
        const logEl = document.createElement('div');
        logEl.className = 'small mono';
        logEl.textContent = r.log.split('\n').map((l) => l.slice(0, 140)).join('\n');
        li.appendChild(logEl);
      }
      list.appendChild(li);
    }
    if (!data.runs.length) list.innerHTML = '<li class="small">No runs yet.</li>';
  } catch { /* offline */ }
}

$('#wf-reload').addEventListener('click', async () => {
  const data = await api('/api/workflows/reload', { method: 'POST', body: {} });
  toast(`Loaded ${data.loaded} workflow(s)`);
  loadWorkflows();
});

/* ── conversation archive ── */
$('#archive-chat').addEventListener('click', async () => {
  if (!conversationId) { toast('Nothing to archive yet — have a conversation first.'); return; }
  const data = await api(`/api/conversations/${conversationId}/archive`, { method: 'POST', body: {} });
  if (data.error) toast(`Archive failed: ${data.error}`);
  else toast(`Archived into memory: ${(data.summary || '').slice(0, 140)}…`);
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
    if (evt.type === 'approval:requested') { approvalToast(evt.payload); loadApprovals(); }
    if (evt.type === 'approval:resolved') { loadApprovals(); toast(`Approval #${evt.payload.id} → ${evt.payload.status}`, 3000); }
    if (evt.type === 'authority:approval-waiting') addToolNote(`${evt.payload.tool} (waiting for your approval…)`);
    if (evt.type === 'workflow:done' || evt.type === 'workflow:failed') {
      toast(`⚡ workflow "${evt.payload.id}" ${evt.type === 'workflow:done' ? 'finished' : 'FAILED'}`);
      loadRuns();
    }
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
loadApprovals();
loadWorkflows();
loadVoiceStatus();
connectEvents();
setInterval(loadHealth, 8000);
setInterval(loadApprovals, 15000);
