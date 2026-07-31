/* JARVIS Holographic Movable UI - Manina Labs Style
   Draggable, resizable, holographic panels
*/

const canvas = document.getElementById('canvas');
const modelPill = document.getElementById('model-pill');

let ws = null;
let panels = [];
let panelIdCounter = 0;
let draggedPanel = null;
let dragOffset = {x:0, y:0};
let resizedPanel = null;
let resizeStart = {x:0, y:0, w:0, h:0};

// Default layouts
const DEFAULT_LAYOUT = [
  { type: 'chat', x: 20, y: 20, w: 420, h: 520 },
  { type: 'codebase', x: 460, y: 20, w: 380, h: 260 },
  { type: 'git', x: 460, y: 300, w: 380, h: 240 },
  { type: 'agent', x: 860, y: 20, w: 400, h: 320 },
  { type: 'proactive', x: 860, y: 360, w: 400, h: 200 },
];

const PANEL_DEFS = {
  chat: { icon: '💬', title: 'Chat — JARVIS', defaultW: 420, defaultH: 520, render: renderChatPanel },
  codebase: { icon: '🧠', title: 'Codebase RAG', defaultW: 380, defaultH: 260, render: renderCodebasePanel },
  git: { icon: '📦', title: 'Git Status', defaultW: 380, defaultH: 240, render: renderGitPanel },
  agent: { icon: '⚡', title: 'Coding Agent', defaultW: 400, defaultH: 320, render: renderAgentPanel },
  team: { icon: '👥', title: 'Multi-Agent Team', defaultW: 400, defaultH: 320, render: renderTeamPanel },
  proactive: { icon: '🌅', title: 'Proactive Briefing', defaultW: 400, defaultH: 200, render: renderProactivePanel },
  memory: { icon: '◐', title: 'Memory', defaultW: 360, defaultH: 280, render: renderMemoryPanel },
  evolution: { icon: '🧬', title: 'Self-Evolution', defaultW: 360, defaultH: 300, render: renderEvolutionPanel },
  terminal: { icon: '🖥️', title: 'Terminal', defaultW: 400, defaultH: 220, render: renderTerminalPanel },
  system: { icon: '📊', title: 'System Stats', defaultW: 320, defaultH: 200, render: renderSystemPanel },
  selfedit: { icon: '🔧', title: 'Self-Edits', defaultW: 380, defaultH: 260, render: renderSelfEditPanel },
  voice: { icon: '🎙️', title: 'Voice Lab', defaultW: 380, defaultH: 300, render: renderVoicePanel },
};

// Connect WS for live data
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/ws`);
  ws.onopen = () => {
    console.log('WS connected for holo UI');
    modelPill.textContent = 'jarvis • online • holo';
  };
  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      // Broadcast to panels
      document.dispatchEvent(new CustomEvent('jarvis-ws', { detail: msg }));
    } catch {}
  };
  ws.onclose = () => setTimeout(connectWS, 2000);
}

// Panel creation
function createPanel(type, x, y, w, h) {
  const def = PANEL_DEFS[type] || PANEL_DEFS.chat;
  const id = `panel-${panelIdCounter++}`;
  const panel = document.createElement('div');
  panel.className = `holo-panel panel-${type}`;
  panel.id = id;
  panel.dataset.type = type;
  panel.style.left = `${x}px`;
  panel.style.top = `${y}px`;
  panel.style.width = `${w || def.defaultW}px`;
  panel.style.height = `${h || def.defaultH}px`;
  panel.style.zIndex = 10 + panelIdCounter;

  panel.innerHTML = `
    <div class="panel-header">
      <div class="title"><span class="icon">${def.icon}</span> ${def.title} <span class="status-dot" style="margin-left:8px"></span></div>
      <div class="panel-controls">
        <button data-action="minimize" title="Minimize">—</button>
        <button data-action="close" title="Close">✕</button>
      </div>
    </div>
    <div class="panel-content" id="${id}-content">Loading ${def.title}, Sir...</div>
    <div class="panel-resize"></div>
  `;

  canvas.appendChild(panel);
  panels.push({ id, type, el: panel, x, y, w, h });

  // Attach drag
  const header = panel.querySelector('.panel-header');
  header.addEventListener('mousedown', (e) => startDrag(e, panel));

  // Resize
  const resizer = panel.querySelector('.panel-resize');
  resizer.addEventListener('mousedown', (e) => startResize(e, panel));

  // Controls
  panel.querySelector('[data-action="close"]').onclick = () => closePanel(id);
  panel.querySelector('[data-action="minimize"]').onclick = () => minimizePanel(panel);

  // Bring to front on click
  panel.addEventListener('mousedown', () => bringToFront(panel));

  // Render content
  setTimeout(() => {
    const contentEl = document.getElementById(`${id}-content`);
    if (contentEl && def.render) def.render(contentEl, id);
  }, 100);

  saveLayout();
  return panel;
}

function closePanel(id) {
  const panel = document.getElementById(id);
  if (panel) {
    panel.style.animation = 'panelIn 0.2s reverse';
    setTimeout(() => {
      panel.remove();
      panels = panels.filter(p => p.id !== id);
      saveLayout();
    }, 200);
  }
}

function minimizePanel(panel) {
  const content = panel.querySelector('.panel-content');
  const isMin = panel.dataset.minimized === 'true';
  if (isMin) {
    content.style.display = '';
    panel.style.height = panel.dataset.prevH || '300px';
    panel.dataset.minimized = 'false';
  } else {
    panel.dataset.prevH = panel.style.height;
    content.style.display = 'none';
    panel.style.height = '44px';
    panel.dataset.minimized = 'true';
  }
}

function bringToFront(panel) {
  let maxZ = 10;
  panels.forEach(p => {
    const z = parseInt(p.el.style.zIndex || 10);
    if (z > maxZ) maxZ = z;
  });
  panel.style.zIndex = maxZ + 1;
}

// Drag logic
function startDrag(e, panel) {
  if (e.target.closest('.panel-controls')) return;
  draggedPanel = panel;
  const rect = panel.getBoundingClientRect();
  dragOffset.x = e.clientX - rect.left;
  dragOffset.y = e.clientY - rect.top;
  panel.classList.add('dragging');
  document.addEventListener('mousemove', onDrag);
  document.addEventListener('mouseup', stopDrag);
  bringToFront(panel);
}

function onDrag(e) {
  if (!draggedPanel) return;
  const x = e.clientX - dragOffset.x;
  const y = e.clientY - dragOffset.y - 54; // topbar offset
  draggedPanel.style.left = `${Math.max(0, x)}px`;
  draggedPanel.style.top = `${Math.max(0, y)}px`;
}

function stopDrag() {
  if (draggedPanel) {
    draggedPanel.classList.remove('dragging');
    // Update panels array
    const entry = panels.find(p => p.id === draggedPanel.id);
    if (entry) {
      entry.x = parseInt(draggedPanel.style.left);
      entry.y = parseInt(draggedPanel.style.top);
    }
    saveLayout();
    draggedPanel = null;
  }
  document.removeEventListener('mousemove', onDrag);
  document.removeEventListener('mouseup', stopDrag);
}

function startResize(e, panel) {
  e.stopPropagation();
  resizedPanel = panel;
  resizeStart.x = e.clientX;
  resizeStart.y = e.clientY;
  resizeStart.w = panel.offsetWidth;
  resizeStart.h = panel.offsetHeight;
  document.addEventListener('mousemove', onResize);
  document.addEventListener('mouseup', stopResize);
}

function onResize(e) {
  if (!resizedPanel) return;
  const dx = e.clientX - resizeStart.x;
  const dy = e.clientY - resizeStart.y;
  const newW = Math.max(280, resizeStart.w + dx);
  const newH = Math.max(150, resizeStart.h + dy);
  resizedPanel.style.width = `${newW}px`;
  resizedPanel.style.height = `${newH}px`;
}

function stopResize() {
  if (resizedPanel) {
    const entry = panels.find(p => p.id === resizedPanel.id);
    if (entry) {
      entry.w = parseInt(resizedPanel.style.width);
      entry.h = parseInt(resizedPanel.style.height);
    }
    saveLayout();
    resizedPanel = null;
  }
  document.removeEventListener('mousemove', onResize);
  document.removeEventListener('mouseup', stopResize);
}

// Layout save/load
function saveLayout() {
  const layout = panels.map(p => ({
    type: p.type,
    x: parseInt(p.el.style.left) || p.x,
    y: parseInt(p.el.style.top) || p.y,
    w: parseInt(p.el.style.width) || p.w,
    h: parseInt(p.el.style.height) || p.h,
  }));
  localStorage.setItem('jarvis-holo-layout', JSON.stringify(layout));
}

function loadLayout() {
  const saved = localStorage.getItem('jarvis-holo-layout');
  if (saved) {
    try {
      const layout = JSON.parse(saved);
      layout.forEach(l => createPanel(l.type, l.x, l.y, l.w, l.h));
      return true;
    } catch {}
  }
  return false;
}

function resetLayout() {
  canvas.innerHTML = '';
  panels = [];
  localStorage.removeItem('jarvis-holo-layout');
  DEFAULT_LAYOUT.forEach(l => createPanel(l.type, l.x, l.y, l.w, l.h));
}

// Panel renderers
function renderChatPanel(el) {
  el.innerHTML = `
    <div class="chat-messages" id="holo-chat-messages" style="flex:1; overflow-y:auto; display:flex; flex-direction:column; gap:8px; max-height:340px">
      <div class="msg jarvis">Good evening, Sir. Holographic movable interface active. Drag me around, Sir. Like Manina Labs style.</div>
    </div>
    <div class="chat-input">
      <input id="holo-chat-input" placeholder="Message JARVIS..."/>
      <button id="holo-chat-send">Send</button>
    </div>
  `;
  const input = el.querySelector('#holo-chat-input');
  const send = el.querySelector('#holo-chat-send');
  const msgs = el.querySelector('#holo-chat-messages');

  function sendMsg() {
    const text = input.value.trim();
    if (!text || !ws) return;
    const div = document.createElement('div');
    div.className = 'msg user';
    div.textContent = text;
    msgs.appendChild(div);
    ws.send(JSON.stringify({ message: text }));
    input.value = '';
    msgs.scrollTop = msgs.scrollHeight;
  }
  send.onclick = sendMsg;
  input.onkeydown = (e) => { if (e.key === 'Enter') sendMsg(); };

  document.addEventListener('jarvis-ws', (e) => {
    const { type, data } = e.detail;
    if (type === 'stream') {
      let last = msgs.querySelector('.msg.jarvis:last-child');
      if (!last || last.dataset.done === 'true') {
        last = document.createElement('div');
        last.className = 'msg jarvis';
        last.textContent = '';
        msgs.appendChild(last);
      }
      last.textContent += data;
      msgs.scrollTop = msgs.scrollHeight;
    } else if (type === 'done') {
      const last = msgs.querySelector('.msg.jarvis:last-child');
      if (last) last.dataset.done = 'true';
    }
  });
}

function renderCodebasePanel(el) {
  el.innerHTML = `<div style="opacity:0.6; font-size:12px">Loading codebase, Sir...</div>`;
  fetch('/api/codebase/overview').then(r=>r.json()).then(data=>{
    if (data.error) { el.innerHTML = `<small style="opacity:0.5">Codebase RAG not ready: ${data.error}</small>`; return; }
    el.innerHTML = `
      <div style="font-size:12px; font-family:'JetBrains Mono'">
        <div>Files: ${data.total_files || 0} | Vectors: ${data.total_vectors || 0}</div>
        <div style="margin-top:8px; opacity:0.7">Tech: ${(data.tech_stack||[]).join(', ')}</div>
        <div style="margin-top:8px">Languages: ${Object.keys(data.languages||{}).slice(0,5).join(', ')}</div>
        <div style="margin-top:12px">
          <input id="code-search" placeholder="Search codebase..." style="width:100%; background:rgba(255,255,255,0.05); border:1px solid var(--panel-border); color:var(--text); padding:8px; border-radius:6px; font-family:inherit; font-size:12px"/>
          <div id="code-results" style="margin-top:8px; max-height:150px; overflow-y:auto"></div>
        </div>
      </div>
    `;
    const input = el.querySelector('#code-search');
    const results = el.querySelector('#code-results');
    input.onkeydown = async (e) => {
      if (e.key === 'Enter') {
        const q = input.value.trim();
        if (!q) return;
        results.innerHTML = '<small style="opacity:0.5">Searching...</small>';
        const resp = await fetch(`/api/codebase/search?query=${encodeURIComponent(q)}&k=3`);
        const data = await resp.json();
        if (!data.results || !data.results.length) { results.innerHTML = '<small>No results</small>'; return; }
        results.innerHTML = data.results.map(r=>`<div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); border-radius:6px; padding:8px; margin-bottom:6px"><small style="opacity:0.6">${r.metadata?.file_path} • ${r.score?.toFixed(2)}</small><br>${r.text.slice(0,200)}...</div>`).join('');
      }
    };
  });
}

function renderGitPanel(el) {
  el.innerHTML = `<small style="opacity:0.6">Loading git, Sir...</small>`;
  fetch('/api/git/status').then(r=>r.json()).then(d=>{
    fetch('/api/git/log?limit=5').then(r2=>r2.json()).then(d2=>{
      el.innerHTML = `
        <div style="font-family:'JetBrains Mono'; font-size:11px; white-space:pre-wrap; background:rgba(0,0,0,0.3); padding:10px; border-radius:8px; max-height:120px; overflow:auto">${(d.status||'').slice(0,800) || 'Clean'}</div>
        <div style="margin-top:10px; font-size:11px; opacity:0.7">Recent commits:<br>${(d2.log||'').slice(0,500)}</div>
      `;
    });
  });
}

function renderAgentPanel(el) {
  el.innerHTML = `
    <div style="display:flex; gap:8px; margin-bottom:10px">
      <input id="agent-task" placeholder="Task: Add JWT auth..." style="flex:1; background:rgba(255,255,255,0.05); border:1px solid var(--panel-border); color:var(--text); padding:8px; border-radius:6px; font-size:12px"/>
      <button id="agent-start" class="holo-btn" style="padding:6px 12px">Start</button>
    </div>
    <div id="agent-log" style="font-family:'JetBrains Mono'; font-size:11px; background:rgba(0,0,0,0.4); padding:10px; border-radius:8px; max-height:180px; overflow-y:auto">Awaiting task, Sir...</div>
  `;
  const input = el.querySelector('#agent-task');
  const btn = el.querySelector('#agent-start');
  const log = el.querySelector('#agent-log');
  function appendLog(txt, type='info') {
    const div = document.createElement('div');
    div.style.color = type==='error'?'#ff6b6b':type==='success'?'#00c950':'#7a8a9a';
    div.textContent = `[${new Date().toLocaleTimeString()}] ${txt}`;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }
  btn.onclick = () => {
    const task = input.value.trim();
    if (!task || !ws) return;
    log.innerHTML = '';
    appendLog(`Starting agent: ${task}`);
    ws.send(JSON.stringify({ type: 'agent', task }));
  };
  document.addEventListener('jarvis-ws', (e)=>{
    const {type, data} = e.detail;
    if (type.startsWith('agent_')) {
      if (type === 'agent_plan') appendLog(`Plan: ${data.todos?.length} steps`, 'info');
      else if (type === 'agent_todo_start') appendLog(`→ ${data.todo?.title}`, 'info');
      else if (type === 'agent_todo_done') appendLog(`✓ ${data.todo?.title} done`, 'success');
      else if (type === 'agent_done') appendLog(`Done in ${data.elapsed_seconds}s: ${data.completed}/${data.todos_total}`, 'success');
      else if (type === 'agent_error') appendLog(`Error: ${data.error}`, 'error');
    }
  });
}

function renderTeamPanel(el) { el.innerHTML = `<small>Multi-agent team panel — same as Agent but with Planner, Researcher, Coder, Reviewer collaborating. Use main UI Team Mode for full UX, Sir. This panel shows live team status.</small><div id="team-mini-log" style="margin-top:10px; font-family:'JetBrains Mono'; font-size:11px; background:rgba(0,0,0,0.3); padding:8px; border-radius:6px; max-height:150px; overflow:auto">Team idle</div>`;
  const log = el.querySelector('#team-mini-log');
  document.addEventListener('jarvis-ws', (e)=>{
    const {type, data} = e.detail;
    if (type.startsWith('team_')) {
      const div = document.createElement('div');
      div.textContent = `[${type.replace('team_','')}] ${data.task || data.todo?.title || data.message || JSON.stringify(data).slice(0,100)}`;
      div.style.opacity = '0.8';
      div.style.padding = '2px 0';
      log.appendChild(div);
      log.scrollTop = log.scrollHeight;
    }
  });
}
function renderProactivePanel(el) {
  el.innerHTML = `<small>Loading briefing, Sir...</small>`;
  fetch('/api/proactive/status').then(r=>r.json()).then(data=>{
    el.innerHTML = `
      <div style="font-size:12px">
        <div>Active: ${data.active ? '✓' : '✗'} | Morning: ${data.morning_time} | Evening: ${data.evening_time}</div>
        <div style="margin-top:8px; background:rgba(0,0,0,0.3); padding:10px; border-radius:8px; max-height:120px; overflow:auto">${(data.last_briefing||'No briefing yet').slice(0,300)}</div>
        <button id="brief-now" class="holo-btn" style="margin-top:8px; width:100%">Trigger Morning Briefing Now</button>
      </div>
    `;
    el.querySelector('#brief-now').onclick = () => {
      fetch('/api/proactive/trigger?type=morning', {method:'POST'}).then(()=>{ el.innerHTML += '<div style="margin-top:6px; color:#00c950; font-size:11px">Briefing triggered, Sir.</div>'; });
    };
  });
}
function renderMemoryPanel(el) { el.innerHTML = `<small>Loading memory, Sir...</small>`; fetch('/api/memories').then(r=>r.json()).then(d=>{ const mems = d.memories||[]; el.innerHTML = mems.slice(-6).reverse().map(m=>`<div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); border-radius:6px; padding:8px; margin-bottom:6px; font-size:12px"><strong>${m.key}</strong>: ${m.value.slice(0,60)}</div>`).join('') || '<small>No memories</small>'; }); }
function renderEvolutionPanel(el) { el.innerHTML = `<small>Loading evolution, Sir...</small>`; fetch('/api/evolution/status').then(r=>r.json()).then(d=>{ el.innerHTML = `<div style="font-size:12px; font-family:'JetBrains Mono'">Evolutions: ${d.evolution_count||0}<br>Critic: ${d.avg_critic_score||'—'}/10<br>Trend: ${d.stats?.trend||'—'}<br>Satisfaction: ${((d.stats?.avg_satisfaction||0.5)*100|0)}%<br><br>Should evolve: ${d.should_evolve ? 'Yes - ' + (d.reasons||[]).join(', ') : 'No, performing well'}</div>`; }); }
function renderTerminalPanel(el) { el.innerHTML = `<div style="display:flex; gap:6px"><input id="term-cmd" placeholder="ls, git status, etc" style="flex:1; background:rgba(0,0,0,0.5); border:1px solid var(--panel-border); color:var(--text); padding:8px; border-radius:6px; font-family:'JetBrains Mono'; font-size:12px"/><button id="term-run" class="holo-btn">Run</button></div><pre id="term-out" style="margin-top:10px; background:rgba(0,0,0,0.5); padding:10px; border-radius:8px; max-height:150px; overflow:auto; font-size:11px">Terminal ready, Sir.</pre>`; const input = el.querySelector('#term-cmd'); const btn = el.querySelector('#term-run'); const out = el.querySelector('#term-out'); async function run(){ const cmd = input.value.trim(); if(!cmd) return; out.textContent = `> ${cmd}\nRunning...`; const resp = await fetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({message: `Execute shell command: ${cmd} using shell_command tool`})}); const data = await resp.json(); out.textContent = data.response?.slice(0,2000) || data.error || 'No output'; }; btn.onclick = run; input.onkeydown = (e)=>{ if(e.key==='Enter') run(); }; }
function renderSystemPanel(el) { el.innerHTML = `<small>Loading system, Sir...</small>`; fetch('/api/status').then(r=>r.json()).then(d=>{ el.innerHTML = `<div style="font-size:12px; font-family:'JetBrains Mono'">Model: ${d.model}<br>Ollama: ${d.ollama_connected?'✓':'✗'}<br>Conversations: ${d.conversation_length}<br>Vectors: ${d.vector_count||0}<br>Memories: ${d.memory_count||0}<br>Evolution: ${d.evolution_count||0}<br>Learning: ${d.learning_enabled?'✓':'✗'}</div>`; }); }
function renderSelfEditPanel(el) { el.innerHTML = `<small>Loading self-edits, Sir...</small>`; fetch('/api/self-edit/history?limit=5').then(r=>r.json()).then(d=>{ const h = d.history||[]; if(!h.length){ el.innerHTML='<small>No self-edits yet</small>'; return;} el.innerHTML = h.slice(-5).reverse().map(e=>`<div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); border-radius:6px; padding:8px; margin-bottom:6px; font-size:11px"><strong>${e.file_path||''}</strong><br>${e.reason||''}<br><small style="opacity:0.5">${e.timestamp?.slice(0,16)} • ${e.success?'✓':'✗'}</small></div>`).join(''); }); }
function renderVoicePanel(el) {
  el.innerHTML = `
    <div style="font-size:12px">
      <div style="margin-bottom:8px">Premium Voice Lab — Manina Labs Style</div>
      <select id="voice-preset-mini" style="width:100%; background:rgba(255,255,255,0.05); border:1px solid var(--panel-border); color:var(--text); padding:8px; border-radius:6px; font-size:12px">
        <option value="manina_premium">Manina Premium — Deep British Cinematic</option>
        <option value="jarvis_classic">Jarvis Classic — Paul Bettany</option>
        <option value="jarvis_deep">Jarvis Deep — Commanding</option>
        <option value="friday">FRIDAY — Irish Female</option>
      </select>
      <div style="display:flex; gap:6px; margin-top:8px">
        <input id="voice-text-mini" placeholder="Text to speak..." style="flex:1; background:rgba(255,255,255,0.05); border:1px solid var(--panel-border); color:var(--text); padding:8px; border-radius:6px; font-size:12px" value="Good evening, Sir. Premium voice model online."/>
        <button id="voice-speak-mini" class="holo-btn">Speak</button>
      </div>
      <small style="opacity:0.5; display:block; margin-top:8px">Edge + premium FX is free, close to Manina. ElevenLabs best quality needs API key.</small>
    </div>
  `;
  const btn = el.querySelector('#voice-speak-mini');
  const input = el.querySelector('#voice-text-mini');
  const preset = el.querySelector('#voice-preset-mini');
  btn.onclick = async () => {
    const text = input.value.trim();
    const pre = preset.value;
    if (!text) return;
    btn.textContent = '...';
    try {
      const resp = await fetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({message: `Speak with premium voice preset ${pre}: ${text} using edge TTS. Just say the text.`})});
      const data = await resp.json();
      // In real implementation, would call /api/tts endpoint, for now just show response
      btn.textContent = 'Speak';
    } catch { btn.textContent = 'Speak'; }
  };
}

// Add panel menu
document.getElementById('add-panel-btn').onclick = () => {
  document.getElementById('panel-menu').classList.toggle('open');
};
document.getElementById('panel-menu-close').onclick = () => {
  document.getElementById('panel-menu').classList.remove('open');
};
document.querySelectorAll('.panel-menu-grid button').forEach(btn=>{
  btn.onclick = () => {
    const type = btn.dataset.type;
    const x = 20 + Math.random()*200;
    const y = 20 + Math.random()*200;
    createPanel(type, x, y);
    document.getElementById('panel-menu').classList.remove('open');
  };
});

// Layout
document.getElementById('layout-save-btn').onclick = () => {
  saveLayout();
  alert('Layout saved, Sir.');
};
document.getElementById('layout-reset-btn').onclick = () => {
  if (confirm('Reset holographic layout, Sir?')) resetLayout();
};

// Voice modal
document.getElementById('voice-preset-btn').onclick = () => {
  document.getElementById('voice-modal').classList.add('open');
  loadVoicePresets();
};
document.getElementById('voice-modal-close').onclick = () => {
  document.getElementById('voice-modal').classList.remove('open');
};
document.getElementById('voice-modal').onclick = (e) => {
  if (e.target.id === 'voice-modal') e.target.classList.remove('open');
};

function loadVoicePresets() {
  const container = document.getElementById('voice-presets');
  const presets = [
    { id: 'manina_premium', name: 'Manina Premium', desc: 'Deep British, cinematic, slight reverb, authoritative - like movie JARVIS. Edge + bass boost + reverb FX. Free, close to Manina Labs premium.' },
    { id: 'jarvis_classic', name: 'Jarvis Classic', desc: 'Classic Paul Bettany - calm, witty, sophisticated. British, RyanNeural with light FX.' },
    { id: 'jarvis_deep', name: 'Jarvis Deep', desc: 'Deeper, more commanding, slower gravitas. GuyNeural + deep pitch shift + bass.' },
    { id: 'friday', name: 'FRIDAY', desc: 'Female Irish, warm, slightly faster, caring. SoniaNeural.' },
  ];
  container.innerHTML = presets.map(p=>`
    <div class="voice-preset" data-preset="${p.id}">
      <div class="name">${p.name}</div>
      <div class="desc">${p.desc}</div>
    </div>
  `).join('');
  container.querySelectorAll('.voice-preset').forEach(el=>{
    el.onclick = () => {
      container.querySelectorAll('.voice-preset').forEach(e=>e.classList.remove('active'));
      el.classList.add('active');
    };
  });
}

document.getElementById('voice-test-btn').onclick = async () => {
  const text = document.getElementById('voice-test-text').value.trim();
  const engine = document.getElementById('voice-engine-select').value;
  const presetEl = document.querySelector('.voice-preset.active');
  const preset = presetEl ? presetEl.dataset.preset : 'manina_premium';
  const status = document.getElementById('voice-status');
  if (!text) return;
  status.textContent = `Generating with ${engine} + ${preset}, Sir...`;
  try {
    // Call backend TTS endpoint if exists, else via chat
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ message: `Use premium TTS engine ${engine} with preset ${preset} to speak: "${text}". Actually just confirm you would speak it with that voice.` })
    });
    const data = await resp.json();
    status.textContent = `Would speak with ${engine} + ${preset}: ${data.response?.slice(0,200) || 'OK'}`;
  } catch (e) {
    status.textContent = `Error: ${e}`;
  }
};

// Init
connectWS();
if (!loadLayout()) {
  DEFAULT_LAYOUT.forEach(l => createPanel(l.type, l.x, l.y, l.w, l.h));
}

// Keyboard: Esc closes menus
document.addEventListener('keydown', (e)=>{
  if (e.key === 'Escape') {
    document.getElementById('panel-menu').classList.remove('open');
    document.getElementById('voice-modal').classList.remove('open');
  }
});
