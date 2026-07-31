/* JARVIS 4.0 - Always-On + Proactive + Multi-Agent + Evolution + Agent */

const chatEl = document.getElementById('chat');
const inputEl = document.getElementById('input');
const sendBtn = document.getElementById('send');
const welcomeEl = document.getElementById('welcome');
const drawer = document.getElementById('drawer');
const drawerOverlay = document.getElementById('drawer-overlay');
const modelSelect = document.getElementById('model-select');
const modelPill = document.getElementById('model-pill');
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');

let ws = null;
let currentModel = 'jarvis';
let startTime = Date.now();
let lastJarvisMsgEl = null;

inputEl.addEventListener('input', () => {
  inputEl.style.height = 'auto';
  inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
});

function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/ws`);
  ws.onopen = () => {
    setStatus(true, 'online');
    modelPill.textContent = currentModel + ' • online';
  };
  ws.onmessage = (e) => {
    try { handleWS(JSON.parse(e.data)); } catch(err){ console.error(err); }
  };
  ws.onclose = () => {
    setStatus(false, 'offline — reconnecting');
    setTimeout(connectWS, 2000);
  };
  ws.onerror = () => setStatus(false, 'error');
}

function handleWS(msg) {
  const { type, data } = msg;
  switch(type) {
    case 'status':
      currentModel = data.model || currentModel;
      modelPill.textContent = currentModel + (data.ollama_connected ? ' • online' : ' • ollama offline');
      document.getElementById('stat-vectors').textContent = data.vector_count || data.memory_count || 0;
      document.getElementById('stat-msgs').textContent = data.conversation_length || 0;
      document.getElementById('stat-satisfaction').textContent = data.satisfaction ? (data.satisfaction*100|0)+'%' : '—';
      document.getElementById('stat-evolutions').textContent = data.evolution_count || 0;
      document.getElementById('stat-critic').textContent = data.avg_critic_score ? data.avg_critic_score : '—';
      document.getElementById('stat-trend').textContent = data.trend || '—';
      document.getElementById('learning-count') && (document.getElementById('learning-count').textContent = data.vector_count || data.learnings_count || 0);
      document.getElementById('evolution-count').textContent = data.evolution_count || 0;
      document.getElementById('evo-badge').textContent = data.evolution_count ? `• v${data.evolution_count} evolved` : '';
      if (data.profile) updateProfileBox(data.profile);
      setStatus(data.ollama_connected, data.ollama_connected ? 'online' : 'ollama offline');
      break;
    case 'message':
      if (data && !data.includes('Online, Sir')) addMessage('jarvis', data);
      hideThinking();
      break;
    case 'stream':
      if (!lastJarvisMsgEl || lastJarvisMsgEl.dataset.done === 'true') {
        lastJarvisMsgEl = addMessage('jarvis', '', true);
      }
      appendToLast(data);
      break;
    case 'learned':
      if (Array.isArray(data) && data.length) {
        showToast(`🧠 Learned: ${data[0].slice(0, 60)}`);
        const badge = document.getElementById('learning-badge');
        const txt = document.getElementById('learning-text');
        if (badge && txt) {
          badge.style.display = 'flex';
          txt.textContent = data[0].slice(0, 80);
          setTimeout(() => badge.style.display = 'none', 6000);
        }
        loadLearnings();
      }
      break;
    case 'tool':
      addMessage('tool', data);
      break;
    case 'evolution':
      addMessage('system', `Evolution: ${JSON.stringify(data, null, 2)}`);
      showToast(`🧬 Evolved: ${data.message || 'Improvement done'}`);
      break;
    case 'evolved':
      showToast(`🧬 ${data.message || 'I made myself better, Sir.'}`);
      loadEvolutionCount();
      break;
    case 'agent_start':
      addMessage('system', `⚡ Agent started: ${data.task}`);
      showToast(`⚡ Agent: ${data.task.slice(0,60)}`);
      break;
    case 'agent_plan':
      handleAgentPlan(data);
      break;
    case 'agent_todo_start':
      handleAgentTodoStart(data);
      break;
    case 'agent_todo_done':
      handleAgentTodoDone(data);
      break;
    case 'agent_todo_failed':
      handleAgentTodoFailed(data);
      break;
    case 'agent_status':
      appendAgentLog(data.message || '', 'info');
      break;
    case 'agent_file_edit':
      appendAgentLog(`Edited: ${data.file || data.path || 'file'}`, 'file');
      break;
    case 'agent_test_result':
      appendAgentLog(`${data.result?.summary || data.message || 'Tests'}`, data.result?.success ? 'success' : 'error');
      break;
    case 'agent_git_commit':
      appendAgentLog(`Committed: ${String(data.result||'').slice(0,100) || 'changes'}`, 'success');
      break;
    case 'agent_done':
      handleAgentDone(data);
      break;
    case 'agent_error':
      appendAgentLog(`Error: ${data.error || data.message}`, 'error');
      break;
    case 'team_start':
      addMessage('system', `👥 Team started: ${data.task}`);
      appendTeamLog(`Team started: ${data.task}`, 'supervisor', 'info');
      showToast(`👥 Team: ${data.task.slice(0,50)}`);
      break;
    case 'team_supervisor_decision':
      appendTeamLog(`Supervisor: ${data.routing?.strategy} - ${data.routing?.reason}`, 'supervisor', 'info');
      break;
    case 'team_plan':
      handleTeamPlan(data);
      addMessage('system', `Team plan: ${data.todos?.length} steps`);
      break;
    case 'team_agent_start':
      appendTeamLog(`→ ${data.todo?.title || data.message}`, data.todo?.agent || data.agent || 'agent', 'info');
      // also update todo UI
      if (data.todo) {
        const el = document.getElementById(`team-todo-${data.todo.id}`);
        if (el) {
          el.classList.add('in_progress');
          const check = el.querySelector('.todo-check');
          if (check) check.textContent = '◐';
        }
      }
      break;
    case 'team_agent_result':
      appendTeamLog(`✓ ${(data.todo?.title||'Result')}: ${String(data.result||'').slice(0,200)}`, data.todo?.agent || 'agent', 'success');
      if (data.todo) {
        const el = document.getElementById(`team-todo-${data.todo.id}`);
        if (el) {
          el.classList.remove('in_progress');
          el.classList.add('done');
          const check = el.querySelector('.todo-check');
          if (check) check.textContent = '✓';
        }
      }
      break;
    case 'team_agent_error':
      appendTeamLog(`✗ Error: ${data.error}`, 'error', 'error');
      break;
    case 'team_team_done':
      appendTeamLog(`Team done in ${data.elapsed_seconds}s: ${data.message}`, 'supervisor', 'success');
      showToast(`👥 Team done in ${data.elapsed_seconds}s`);
      addMessage('system', `Team finished: ${data.message}\nAgents: ${(data.agents_used||[]).join(', ')}`);
      break;
    case 'briefing':
      const preview = document.getElementById('briefing-preview');
      if (preview) {
        preview.style.display = 'block';
        preview.textContent = data.text;
      }
      addMessage('system', `🌅 ${data.type} briefing:\n${data.text}`);
      showToast(`${data.type} briefing ready`);
      break;
    case 'thinking':
      showThinking();
      break;
    case 'reflection':
      addMessage('system', `Reflection: ${JSON.stringify(data, null, 2)}`);
      hideThinking();
      break;
    case 'done':
      hideThinking();
      if (lastJarvisMsgEl) lastJarvisMsgEl.dataset.done = 'true';
      lastJarvisMsgEl = null;
      break;
    case 'clear':
      chatEl.innerHTML = '';
      if (welcomeEl) {
        chatEl.appendChild(welcomeEl);
        welcomeEl.style.display = 'flex';
      }
      break;
    case 'error':
      addMessage('system', 'Error: ' + data);
      hideThinking();
      break;
  }
}

function setStatus(online, text) {
  statusText.textContent = text;
  statusDot.classList.toggle('offline', !online);
  const dot = document.querySelector('#status-dot .dot');
  if (dot) dot.style.background = online ? 'var(--green)' : 'var(--orange)';
}

function addMessage(role, text, isStreaming = false) {
  if (welcomeEl) welcomeEl.style.display = 'none';
  const msg = document.createElement('div');
  msg.className = `msg ${role}`;
  if (isStreaming) msg.dataset.streaming = 'true';
  const meta = role === 'user' ? 'You' : role === 'jarvis' ? 'JARVIS' : role === 'tool' ? 'TOOL' : 'SYSTEM';
  const time = new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
  msg.innerHTML = `
    <div class="meta">${meta} • ${time}</div>
    <div class="bubble">${formatText(text)}</div>
    ${role === 'jarvis' ? `
    <div class="msg-actions">
      <button onclick="copyText(this)" title="Copy">⎙</button>
      <button onclick="feedback(this, 'positive')" title="Good">↑</button>
      <button onclick="feedback(this, 'negative')" title="Bad">↓</button>
    </div>` : ''}
  `;
  chatEl.appendChild(msg);
  chatEl.scrollTo({ top: chatEl.scrollHeight, behavior: 'smooth' });
  return msg;
}

function appendToLast(chunk) {
  if (!lastJarvisMsgEl) lastJarvisMsgEl = addMessage('jarvis', '', true);
  const bubble = lastJarvisMsgEl.querySelector('.bubble');
  bubble.textContent += chunk;
  chatEl.scrollTo({ top: chatEl.scrollHeight });
}

function formatText(t) {
  if (!t) return '';
  let e = t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  e = e.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
  e = e.replace(/`([^`]+)`/g, '<code>$1</code>');
  e = e.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  e = e.replace(/\n/g, '<br>');
  return e;
}

let thinkingEl = null;
function showThinking() {
  hideThinking();
  thinkingEl = document.createElement('div');
  thinkingEl.className = 'msg jarvis';
  thinkingEl.innerHTML = `<div class="meta">JARVIS • thinking</div><div class="bubble" style="padding:10px 16px"><div class="thinking"><span></span><span></span><span></span></div></div>`;
  chatEl.appendChild(thinkingEl);
  chatEl.scrollTo({ top: chatEl.scrollHeight });
}
function hideThinking() { if (thinkingEl) { thinkingEl.remove(); thinkingEl = null; } }

function sendMessage() {
  const text = inputEl.value.trim();
  if (!text || !ws || ws.readyState !== 1) return;
  if (text.startsWith('/agent ')) {
    const task = text.slice(7).trim();
    if (!task) return;
    document.getElementById('agent-modal').classList.add('open');
    document.getElementById('agent-task-input').value = task;
    document.getElementById('agent-start-btn').click();
    inputEl.value = '';
    inputEl.style.height = 'auto';
    return;
  }
  if (text.startsWith('/team ')) {
    const task = text.slice(6).trim();
    if (!task) return;
    document.getElementById('team-modal').classList.add('open');
    document.getElementById('team-task-input').value = task;
    inputEl.value = '';
    inputEl.style.height = 'auto';
    return;
  }
  addMessage('user', text);
  ws.send(JSON.stringify({ message: text, model: currentModel }));
  inputEl.value = '';
  inputEl.style.height = 'auto';
  inputEl.focus();
}

sendBtn.onclick = sendMessage;
inputEl.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});

document.querySelectorAll('.suggestions button').forEach(btn => {
  btn.onclick = () => { inputEl.value = btn.dataset.q; sendMessage(); };
});

function openDrawer() {
  drawer.classList.add('open');
  drawerOverlay.classList.add('open');
  loadMemories();
  loadProfile();
  loadProactiveStatus();
}
function closeDrawer() {
  drawer.classList.remove('open');
  drawerOverlay.classList.remove('open');
}
document.getElementById('drawer-btn').onclick = openDrawer;
document.getElementById('drawer-close').onclick = closeDrawer;
drawerOverlay.onclick = closeDrawer;

modelSelect.onchange = () => { currentModel = modelSelect.value; modelPill.textContent = currentModel; };

let synth = window.speechSynthesis;
document.getElementById('voice-toggle').onclick = (e) => {
  const enabled = e.target.textContent.includes('Off');
  e.target.textContent = `Voice: ${enabled ? 'On' : 'Off'}`;
};

function copyText(btn) {
  const bubble = btn.closest('.msg').querySelector('.bubble');
  navigator.clipboard.writeText(bubble.textContent);
  showToast('Copied');
}
function feedback(btn, type) {
  const bubble = btn.closest('.msg').querySelector('.bubble');
  const text = bubble.textContent;
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: 'feedback', feedback: type, text }));
  else fetch('/api/feedback', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ feedback: type, message_text: text }) });
  showToast(type === 'positive' ? 'Thanks, Sir.' : 'Noted, will improve.');
}
function clearChat() {
  if (ws) ws.send(JSON.stringify({ message: '/clear' }));
  chatEl.innerHTML = '';
  if (welcomeEl) { chatEl.appendChild(welcomeEl); welcomeEl.style.display = 'flex'; }
}
function clearLearnings() {
  if (!confirm('Clear all learnings? Resets memory of you, Sir.')) return;
  fetch('/api/clear?clear_learnings=true', { method: 'POST' }).then(() => { showToast('Learnings cleared'); loadLearnings(); });
}
function showToast(text) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = text;
  container.appendChild(toast);
  setTimeout(() => { toast.style.opacity = '0'; toast.style.transform = 'translateY(10px)'; setTimeout(() => toast.remove(), 300); }, 3000);
}
async function loadMemories() {
  try {
    const resp = await fetch('/api/memories');
    const data = await resp.json();
    const list = document.getElementById('memory-list');
    if (!data.memories || !data.memories.length) { list.innerHTML = '<small style="opacity:0.5">No memories yet</small>'; return; }
    list.innerHTML = data.memories.slice(-8).reverse().map(m => `<div class="memory-item"><strong>${m.key}</strong> ${m.value.slice(0,80)}</div>`).join('');
  } catch {}
}
async function loadProfile() {
  try {
    const resp = await fetch('/api/profile');
    const data = await resp.json();
    if (data && !data.error) updateProfileBox(data);
  } catch {}
}
function updateProfileBox(profile) {
  const box = document.getElementById('profile-summary');
  if (!profile) return;
  let lines = [];
  if (profile.preferred_name) lines.push(`Name: ${profile.preferred_name}`);
  if (profile.facts && profile.facts.length) profile.facts.slice(-4).forEach(f => lines.push(`${f.key}: ${f.value}`));
  if (profile.preferences) {
    const prefs = profile.preferences;
    if (prefs.communication_style) lines.push(`Style: ${prefs.communication_style}`);
    if (prefs.topics_of_interest && prefs.topics_of_interest.length) lines.push(`Interests: ${prefs.topics_of_interest.slice(0,3).join(', ')}`);
  }
  box.textContent = lines.length ? lines.join('\n') : 'Learning about you, Sir...';
}
async function loadLearnings() {
  try {
    const resp = await fetch('/api/learnings?limit=20');
    const data = await resp.json();
    const count = data.learnings?.length || 0;
    const el = document.getElementById('learning-count');
    if (el) el.textContent = count;
    const stat = document.getElementById('stat-vectors');
    if (stat) stat.textContent = count;
  } catch {}
}
async function loadEvolutionCount() {
  try {
    const resp = await fetch('/api/evolution/status');
    const data = await resp.json();
    const ec = document.getElementById('evolution-count');
    if (ec) ec.textContent = data.evolution_count || 0;
    const es = document.getElementById('stat-evolutions');
    if (es) es.textContent = data.evolution_count || 0;
  } catch {}
}

// Learnings modal
document.getElementById('learning-btn').onclick = async () => {
  document.getElementById('learnings-modal').classList.add('open');
  const body = document.getElementById('learnings-body');
  body.innerHTML = 'Loading...';
  try {
    const resp = await fetch('/api/learnings?limit=50');
    const data = await resp.json();
    if (!data.learnings || !data.learnings.length) { body.innerHTML = '<p style="opacity:0.6">No learnings yet, Sir. Talk to me and I will learn.</p>'; return; }
    body.innerHTML = data.learnings.map(l => `<div class="memory-item"><small>${new Date(l.timestamp).toLocaleString()}</small><br><strong>${l.metadata?.type || 'memory'}</strong>: ${l.text}</div>`).join('');
  } catch (e) { body.innerHTML = 'Failed: ' + e; }
};
document.getElementById('learnings-close').onclick = () => document.getElementById('learnings-modal').classList.remove('open');
document.getElementById('learnings-modal').onclick = (e) => { if (e.target.id === 'learnings-modal') e.target.classList.remove('open'); };

// Evolution modal
document.getElementById('evolution-btn').onclick = async () => {
  document.getElementById('evolution-modal').classList.add('open');
  const body = document.getElementById('evolution-body');
  body.innerHTML = 'Loading evolution history, Sir...';
  try {
    const resp = await fetch('/api/evolution/history?limit=20');
    const data = await resp.json();
    const history = data.history || [];
    if (!history.length) { body.innerHTML = '<p style="opacity:0.6">No evolutions yet. I will evolve when I detect I can be better, or say "Improve yourself".</p>'; return; }
    body.innerHTML = history.map(h => `<div class="memory-item"><small>${(h.timestamp||'').slice(0,16)} • ${h.type}</small><br><strong>${(h.description||'').slice(0,100)}</strong></div>`).join('');
  } catch (e) { body.innerHTML = 'Failed: ' + e; }
};
document.getElementById('evolution-close').onclick = () => document.getElementById('evolution-modal').classList.remove('open');
document.getElementById('evolution-modal').onclick = (e) => { if (e.target.id === 'evolution-modal') e.target.classList.remove('open'); };

// Reflect etc
document.getElementById('btn-reflect').onclick = async () => {
  showToast('Reflecting, Sir...');
  try {
    const resp = await fetch('/api/reflect', { method: 'POST' });
    const data = await resp.json();
    showToast('Reflection done');
    addMessage('system', `Reflection: ${JSON.stringify(data.insights || data, null, 2)}`);
  } catch { showToast('Reflection failed'); }
};
document.getElementById('btn-learnings').onclick = () => document.getElementById('learning-btn').click();
document.getElementById('btn-evolve').onclick = async () => {
  showToast('🧬 Evolving myself, Sir...');
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: 'evolve', instruction: 'General self-improvement' }));
  else {
    try {
      const resp = await fetch('/api/evolution/improve', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ instruction: 'General self-improvement' }) });
      const data = await resp.json();
      showToast('Evolution started');
      addMessage('system', `Evolution: ${JSON.stringify(data, null, 2)}`);
    } catch { showToast('Evolution failed'); }
  }
};
document.getElementById('btn-evolution-history').onclick = () => document.getElementById('evolution-btn').click();
document.getElementById('btn-analyze').onclick = async () => {
  showToast('Analyzing, Sir...');
  try {
    const resp = await fetch('/api/evolution/status');
    const data = await resp.json();
    addMessage('system', `Performance Analysis:\n${JSON.stringify(data, null, 2)}`);
  } catch { showToast('Analyze failed'); }
};

// Agent handlers
function handleAgentPlan(data) {
  const todos = data.todos || [];
  const planEl = document.getElementById('agent-plan');
  const todosEl = document.getElementById('agent-todos');
  if (planEl) planEl.style.display = 'block';
  if (!todosEl) return;
  todosEl.innerHTML = todos.map(t => `<div class="agent-todo" id="todo-${t.id}"><div class="todo-check">${t.id}</div><div><div class="todo-title">${t.title}</div><div class="todo-desc">${t.description}</div></div></div>`).join('');
  appendAgentLog(`Plan: ${todos.length} steps`, 'info');
}
function handleAgentTodoStart(data) {
  const todo = data.todo || data;
  const el = document.getElementById(`todo-${todo.id}`);
  if (el) { el.classList.add('in_progress'); const c = el.querySelector('.todo-check'); if (c) c.textContent = '◐'; }
  appendAgentLog(`→ ${todo.title}`, 'info');
}
function handleAgentTodoDone(data) {
  const todo = data.todo || data;
  const el = document.getElementById(`todo-${todo.id}`);
  if (el) { el.classList.remove('in_progress'); el.classList.add('done'); const c = el.querySelector('.todo-check'); if (c) c.textContent = '✓'; }
  appendAgentLog(`✓ ${todo.title} done`, 'success');
}
function handleAgentTodoFailed(data) {
  const todo = data.todo || data;
  const el = document.getElementById(`todo-${todo.id}`);
  if (el) { el.style.borderColor = '#ff6b6b'; const c = el.querySelector('.todo-check'); if (c) c.textContent = '✗'; }
  appendAgentLog(`✗ ${todo.title} failed`, 'error');
}
function handleAgentDone(data) {
  appendAgentLog(`Agent done: ${data.completed}/${data.todos_total} in ${data.elapsed_seconds}s`, data.failed ? 'error' : 'success');
  showToast(`⚡ Agent done: ${data.completed}/${data.todos_total}`);
  addMessage('system', `Agent finished: ${data.message}`);
}
function appendAgentLog(text, type='info') {
  const logEl = document.getElementById('agent-log');
  if (!logEl) return;
  if (logEl.textContent.includes('Awaiting task')) logEl.innerHTML = '';
  const line = document.createElement('div');
  line.className = `agent-log-line ${type}`;
  line.textContent = `[${new Date().toLocaleTimeString()}] ${text}`;
  logEl.appendChild(line);
  logEl.scrollTop = logEl.scrollHeight;
}
document.getElementById('agent-btn').onclick = () => document.getElementById('agent-modal').classList.add('open');
document.getElementById('agent-close').onclick = () => document.getElementById('agent-modal').classList.remove('open');
document.getElementById('agent-modal').onclick = (e) => { if (e.target.id === 'agent-modal') e.target.classList.remove('open'); };
document.getElementById('agent-start-btn').onclick = () => {
  const taskInput = document.getElementById('agent-task-input');
  const task = taskInput.value.trim();
  if (!task) return;
  document.getElementById('agent-plan').style.display = 'none';
  document.getElementById('agent-todos').innerHTML = '';
  document.getElementById('agent-log').innerHTML = '';
  appendAgentLog(`Starting agent: ${task}`, 'info');
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: 'agent', task: task }));
};

// Team handlers
function handleTeamPlan(data) {
  const todos = data.todos || [];
  const planEl = document.getElementById('team-plan');
  const todosEl = document.getElementById('team-todos');
  if (planEl) planEl.style.display = 'block';
  if (!todosEl) return;
  todosEl.innerHTML = todos.map(t => `<div class="agent-todo" id="team-todo-${t.id}"><div class="todo-check">${t.id}</div><div><div class="todo-title">[${t.agent}] ${t.title}</div><div class="todo-desc">${t.description}</div></div></div>`).join('');
}
function appendTeamLog(text, agent='supervisor', type='info') {
  const logEl = document.getElementById('team-log');
  if (!logEl) return;
  if (logEl.textContent.includes('Team awaiting')) logEl.innerHTML = '';
  const line = document.createElement('div');
  line.className = `agent-log-line ${type}`;
  line.innerHTML = `<span style="opacity:0.5">[${new Date().toLocaleTimeString()}] [${agent}]</span> ${text}`;
  logEl.appendChild(line);
  logEl.scrollTop = logEl.scrollHeight;
}
document.getElementById('team-btn').onclick = () => { document.getElementById('team-modal').classList.add('open'); loadProactiveStatus(); };
document.getElementById('team-close').onclick = () => document.getElementById('team-modal').classList.remove('open');
document.getElementById('team-modal').onclick = (e) => { if (e.target.id === 'team-modal') e.target.classList.remove('open'); };
document.getElementById('team-start-btn').onclick = () => {
  const taskInput = document.getElementById('team-task-input');
  const task = taskInput.value.trim();
  if (!task) return;
  document.getElementById('team-plan').style.display = 'none';
  document.getElementById('team-todos').innerHTML = '';
  document.getElementById('team-log').innerHTML = '';
  appendTeamLog(`Starting team for: ${task}`, 'supervisor', 'info');
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: 'team', task: task }));
};

// Proactive
document.getElementById('proactive-btn').onclick = () => { document.getElementById('proactive-modal').classList.add('open'); loadProactiveStatus(); };
document.getElementById('proactive-close').onclick = () => document.getElementById('proactive-modal').classList.remove('open');
document.getElementById('proactive-modal').onclick = (e) => { if (e.target.id === 'proactive-modal') e.target.classList.remove('open'); };

async function loadProactiveStatus() {
  try {
    const resp = await fetch('/api/proactive/status');
    const data = await resp.json();
    const statusEl = document.getElementById('proactive-status');
    if (data.error) { statusEl.innerHTML = `<small style="opacity:0.5">Proactive error: ${data.error}</small>`; return; }
    statusEl.innerHTML = `
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:12px">
        <div>Active: ${data.active ? '✓' : '✗'}</div>
        <div>Morning: ${data.morning_time}</div>
        <div>Evening: ${data.evening_time}</div>
        <div>Git watcher: ${data.git_watcher_active ? '✓' : '✗'}</div>
        <div>Dirty: ${data.git_status?.changed_files || 0}</div>
        <div>Jobs: ${data.jobs?.length || 0}</div>
      </div>
    `;
    const wStatus = document.getElementById('wakeword-status');
    if (wStatus) wStatus.textContent = data.active ? 'active' : 'idle';
    const pStatus = document.getElementById('proactive-status-text');
    if (pStatus) pStatus.textContent = data.active ? 'active' : 'offline';
    if (data.last_briefing) {
      const preview = document.getElementById('briefing-preview');
      if (preview) { preview.style.display = 'block'; preview.textContent = data.last_briefing.slice(0,400) + '...'; }
    }
  } catch {}
  try {
    const resp = await fetch('/api/wakeword/status');
    const data = await resp.json();
    const wStatus = document.getElementById('wakeword-status');
    if (wStatus) wStatus.textContent = data.is_running ? `running (${data.engine})` : 'offline';
    const wEng = document.getElementById('wakeword-engine');
    if (wEng) wEng.textContent = data.engine || '-';
    const resp2 = await fetch('/api/codebase/overview');
    const data2 = await resp2.json();
    if (!data2.error) {
      const cs = document.getElementById('codebase-status');
      if (cs) cs.textContent = `${data2.total_files || 0} files`;
    }
  } catch {}
}

function triggerBriefing(type) {
  if (ws && ws.readyState === 1) {
    ws.send(JSON.stringify({ type: 'proactive_briefing', briefing_type: type }));
    showToast(`Generating ${type} briefing...`);
  } else {
    fetch('/api/proactive/briefing?type=' + type, { method: 'POST' })
      .then(r=>r.json()).then(data=>{
        const preview = document.getElementById('briefing-preview');
        if (preview) { preview.style.display = 'block'; preview.textContent = data.text || JSON.stringify(data); }
        showToast(`${type} briefing ready`);
      });
  }
}
document.getElementById('btn-morning-brief').onclick = () => triggerBriefing('morning');
document.getElementById('btn-evening-summary').onclick = () => triggerBriefing('evening');
document.getElementById('btn-trigger-briefing').onclick = () => triggerBriefing('morning');
document.getElementById('btn-always-on-test').onclick = () => {
  showToast('Check wake word: /api/wakeword/status');
  fetch('/api/wakeword/status').then(r=>r.json()).then(d=> addMessage('system', `Wakeword: ${JSON.stringify(d, null, 2)}`));
};

// Init
connectWS();
loadLearnings();
loadEvolutionCount();
setTimeout(() => {
  fetch('/api/status').then(r=>r.json()).then(s=>{
    if (s.model) {
      currentModel = s.model;
      modelPill.textContent = s.model + (s.ollama_connected ? ' • online' : ' • offline');
      modelSelect.value = s.model;
      setStatus(s.ollama_connected, s.ollama_connected ? 'online' : 'ollama offline');
    }
  }).catch(()=> setStatus(false, 'cannot reach server'));
  loadProactiveStatus();
}, 800);

setInterval(() => {
  const diff = Math.floor((Date.now() - startTime)/1000);
  const h = String(Math.floor(diff/3600)).padStart(2,'0');
  const m = String(Math.floor((diff%3600)/60)).padStart(2,'0');
  const s = String(diff%60).padStart(2,'0');
  const upEl = document.getElementById('uptime');
  if (upEl) upEl.textContent = `${h}:${m}:${s}`;
}, 1000);

document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); if (drawer.classList.contains('open')) closeDrawer(); else openDrawer(); }
  if (e.key === 'Escape') {
    if (drawer.classList.contains('open')) closeDrawer();
    document.querySelectorAll('.modal-overlay.open').forEach(m=> m.classList.remove('open'));
  }
});

function loadEvolutionCount() {
  fetch('/api/evolution/status').then(r=>r.json()).then(d=>{
    const ec = document.getElementById('evolution-count');
    if (ec) ec.textContent = d.evolution_count || 0;
    const es = document.getElementById('stat-evolutions');
    if (es) es.textContent = d.evolution_count || 0;
  }).catch(()=>{});
}
