/* JARVIS 2.0 - Minimal Clean UI + Self-Learning */

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
let messageCount = 0;
let startTime = Date.now();
let voiceEnabled = false;
let lastJarvisMsgEl = null;

// Auto-resize textarea
inputEl.addEventListener('input', () => {
  inputEl.style.height = 'auto';
  inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
});

// Connect WS
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
      const s = data;
      currentModel = s.model || currentModel;
      modelPill.textContent = currentModel + (s.ollama_connected ? ' • online' : ' • ollama offline');
      document.getElementById('stat-vectors').textContent = s.vector_count || s.memory_count || 0;
      document.getElementById('stat-msgs').textContent = s.conversation_length || 0;
      document.getElementById('stat-satisfaction').textContent = s.satisfaction ? (s.satisfaction*100|0)+'%' : '—';
      document.getElementById('stat-evolutions').textContent = s.evolution_count || 0;
      document.getElementById('stat-critic').textContent = s.avg_critic_score ? s.avg_critic_score : '—';
      document.getElementById('stat-trend').textContent = s.trend || '—';
      document.getElementById('learning-count').textContent = s.vector_count || s.learnings_count || 0;
      document.getElementById('evolution-count').textContent = s.evolution_count || 0;
      document.getElementById('evo-badge').textContent = s.evolution_count ? `• v${s.evolution_count} evolved` : '';
      if (s.profile) updateProfileBox(s.profile);
      setStatus(s.ollama_connected, s.ollama_connected ? 'online' : 'ollama offline');
      break;

    case 'message':
      if (data && data !== 'Online, Sir.') addMessage('jarvis', data);
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
        document.getElementById('learning-badge').style.display = 'flex';
        document.getElementById('learning-text').textContent = data[0].slice(0, 80);
        setTimeout(() => {
          document.getElementById('learning-badge').style.display = 'none';
        }, 6000);
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
      messageCount++;
      break;

    case 'clear':
      chatEl.innerHTML = '';
      welcomeEl.style.display = 'flex';
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
  document.querySelector('#status-dot .dot').style.background = online ? 'var(--green)' : 'var(--orange)';
}

// Messages - Minimal bubbles
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
  if (!lastJarvisMsgEl) {
    lastJarvisMsgEl = addMessage('jarvis', '', true);
  }
  const bubble = lastJarvisMsgEl.querySelector('.bubble');
  // Streaming raw append, keep formatting minimal
  bubble.textContent += chunk;
  chatEl.scrollTo({ top: chatEl.scrollHeight });
}

function formatText(t) {
  if (!t) return '';
  let e = t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  // Code blocks
  e = e.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
  // Inline code
  e = e.replace(/`([^`]+)`/g, '<code>$1</code>');
  // Bold
  e = e.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  // Line breaks
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
function hideThinking() {
  if (thinkingEl) { thinkingEl.remove(); thinkingEl = null; }
}

// Send
function sendMessage() {
  const text = inputEl.value.trim();
  if (!text || !ws || ws.readyState !== 1) return;

  addMessage('user', text);
  ws.send(JSON.stringify({ message: text, model: currentModel }));

  inputEl.value = '';
  inputEl.style.height = 'auto';
  inputEl.focus();
}

sendBtn.onclick = sendMessage;
inputEl.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

// Suggestions quick
document.querySelectorAll('.suggestions button').forEach(btn => {
  btn.onclick = () => {
    inputEl.value = btn.dataset.q;
    sendMessage();
  };
});

// Drawer
function openDrawer() {
  drawer.classList.add('open');
  drawerOverlay.classList.add('open');
  loadMemories();
  loadProfile();
}
function closeDrawer() {
  drawer.classList.remove('open');
  drawerOverlay.classList.remove('open');
}
document.getElementById('drawer-btn').onclick = openDrawer;
document.getElementById('drawer-close').onclick = closeDrawer;
drawerOverlay.onclick = closeDrawer;

// Model change
modelSelect.onchange = () => {
  currentModel = modelSelect.value;
  modelPill.textContent = currentModel;
};

// Voice toggle
let synth = window.speechSynthesis;
document.getElementById('voice-toggle').onclick = (e) => {
  voiceEnabled = !voiceEnabled;
  e.target.textContent = `Voice: ${voiceEnabled ? 'On' : 'Off'}`;
};

function copyText(btn) {
  const bubble = btn.closest('.msg').querySelector('.bubble');
  navigator.clipboard.writeText(bubble.textContent);
  showToast('Copied');
}

function feedback(btn, type) {
  const bubble = btn.closest('.msg').querySelector('.bubble');
  const text = bubble.textContent;
  if (ws && ws.readyState === 1) {
    ws.send(JSON.stringify({ type: 'feedback', feedback: type, text }));
  } else {
    fetch('/api/feedback', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ feedback: type, message_text: text })
    });
  }
  showToast(type === 'positive' ? 'Thanks for feedback, Sir.' : 'Noted. I will improve, Sir.');
}

function clearChat() {
  if (ws) ws.send(JSON.stringify({ message: '/clear' }));
  chatEl.innerHTML = '';
  if (welcomeEl) {
    chatEl.appendChild(welcomeEl);
    welcomeEl.style.display = 'flex';
  }
}

function clearLearnings() {
  if (!confirm('Clear all learnings? This resets JARVIS memory of you, Sir.')) return;
  fetch('/api/clear?clear_learnings=true', { method: 'POST' }).then(() => {
    showToast('Learnings cleared');
    loadLearnings();
  });
}

// Toast
function showToast(text) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = text;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// Load memories
async function loadMemories() {
  try {
    const resp = await fetch('/api/memories');
    const data = await resp.json();
    const list = document.getElementById('memory-list');
    if (!data.memories || !data.memories.length) {
      list.innerHTML = '<small style="opacity:0.5">No memories yet</small>';
      return;
    }
    list.innerHTML = data.memories.slice(-8).reverse().map(m =>
      `<div class="memory-item"><strong>${m.key}</strong> ${m.value.slice(0,80)}</div>`
    ).join('');
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
  if (profile.facts && profile.facts.length) {
    profile.facts.slice(-4).forEach(f => lines.push(`${f.key}: ${f.value}`));
  }
  if (profile.preferences) {
    const prefs = profile.preferences;
    if (prefs.communication_style) lines.push(`Style: ${prefs.communication_style}`);
    if (prefs.topics_of_interest && prefs.topics_of_interest.length) lines.push(`Interests: ${prefs.topics_of_interest.slice(0,3).join(', ')}`);
  }
  if (!lines.length) box.textContent = 'Learning about you, Sir...';
  else box.textContent = lines.join('\n');
}

async function loadLearnings() {
  try {
    const resp = await fetch('/api/learnings?limit=20');
    const data = await resp.json();
    const count = data.learnings?.length || 0;
    document.getElementById('learning-count').textContent = count;
    document.getElementById('stat-vectors').textContent = count;
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
    if (!data.learnings || !data.learnings.length) {
      body.innerHTML = '<p style="opacity:0.6">No learnings yet, Sir. Talk to me and I will learn automatically.</p>';
      return;
    }
    body.innerHTML = data.learnings.map(l =>
      `<div class="memory-item"><small>${new Date(l.timestamp).toLocaleString()}</small><br><strong>${l.metadata?.type || 'memory'}</strong>: ${l.text}</div>`
    ).join('');

    if (data.insights) {
      const insp = data.insights;
      body.innerHTML += `<hr style="margin:16px 0; border-color: var(--border)"><h4 style="font-size:12px; text-transform:uppercase; opacity:0.6; margin-bottom:8px">Insights</h4><div class="profile-box">${JSON.stringify(insp, null, 2)}</div>`;
    }
  } catch (e) {
    body.innerHTML = 'Failed to load: ' + e;
  }
};
document.getElementById('learnings-close').onclick = () => {
  document.getElementById('learnings-modal').classList.remove('open');
};
document.getElementById('learnings-modal').onclick = (e) => {
  if (e.target.id === 'learnings-modal') e.target.classList.remove('open');
};

// Evolution modal
async function loadEvolutionCount() {
  try {
    const resp = await fetch('/api/evolution/status');
    const data = await resp.json();
    document.getElementById('evolution-count').textContent = data.evolution_count || 0;
    document.getElementById('stat-evolutions').textContent = data.evolution_count || 0;
  } catch {}
}
document.getElementById('evolution-btn').onclick = async () => {
  document.getElementById('evolution-modal').classList.add('open');
  const body = document.getElementById('evolution-body');
  body.innerHTML = 'Loading evolution history, Sir...';
  try {
    const resp = await fetch('/api/evolution/history?limit=20');
    const data = await resp.json();
    const history = data.history || data.prompt_evolutions || [];
    if (!history.length && !data.tool_forges) {
      body.innerHTML = '<p style="opacity:0.6">No evolutions yet, Sir. I will evolve when I detect I can be better, or say "Improve yourself".<br><br>Capabilities:<br>- Self-critique (scores own responses)<br>- Prompt evolution<br>- Tool forging<br>- Memory optimization<br>- Performance tracking</p>';
      return;
    }
    let html = '';
    if (data.history) {
      html += data.history.map(h => `<div class="memory-item"><small>${h.timestamp?.slice(0,16)} • ${h.type}</small><br><strong>${h.description?.slice(0,100)}</strong><br><small>${JSON.stringify(h.details || {}).slice(0,200)}</small></div>`).join('');
    } else {
      if (data.prompt_evolutions) {
        html += '<h4 style="font-size:11px;opacity:0.6;margin:12px 0 6px">PROMPT EVOLUTIONS</h4>';
        html += data.prompt_evolutions.map(p => `<div class="memory-item"><small>${p.timestamp?.slice(0,16)}</small><br>${p.prompt}</div>`).join('');
      }
      if (data.tool_forges) {
        html += '<h4 style="font-size:11px;opacity:0.6;margin:12px 0 6px">TOOL FORGES</h4>';
        html += data.tool_forges.map(t => `<div class="memory-item"><small>${t.timestamp?.slice(0,16)}</small><br><strong>${t.tool_name}</strong>: ${t.reason?.slice(0,80)}</div>`).join('');
      }
    }
    body.innerHTML = html || 'No evolutions yet';
  } catch (e) {
    body.innerHTML = 'Failed: ' + e;
  }
};
document.getElementById('evolution-close').onclick = () => {
  document.getElementById('evolution-modal').classList.remove('open');
};
document.getElementById('evolution-modal').onclick = (e) => {
  if (e.target.id === 'evolution-modal') e.target.classList.remove('open');
};

// Reflect
document.getElementById('btn-reflect').onclick = async () => {
  showToast('Reflecting, Sir...');
  try {
    const resp = await fetch('/api/reflect', { method: 'POST' });
    const data = await resp.json();
    showToast('Reflection done');
    addMessage('system', `Reflection: ${JSON.stringify(data.insights || data, null, 2)}`);
  } catch { showToast('Reflection failed'); }
};
document.getElementById('btn-learnings').onclick = () => {
  document.getElementById('learning-btn').click();
};
document.getElementById('btn-evolve').onclick = async () => {
  showToast('🧬 Evolving myself, Sir...');
  if (ws && ws.readyState === 1) {
    ws.send(JSON.stringify({ type: 'evolve', instruction: 'General self-improvement' }));
  } else {
    try {
      const resp = await fetch('/api/evolution/improve', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ instruction: 'General self-improvement' })
      });
      const data = await resp.json();
      showToast('Evolution started');
      addMessage('system', `Evolution: ${JSON.stringify(data, null, 2)}`);
    } catch { showToast('Evolution failed'); }
  }
};
document.getElementById('btn-evolution-history').onclick = () => {
  document.getElementById('evolution-btn').click();
};
document.getElementById('btn-analyze').onclick = async () => {
  showToast('Analyzing performance, Sir...');
  try {
    const resp = await fetch('/api/evolution/status');
    const data = await resp.json();
    addMessage('system', `Performance Analysis:\n${JSON.stringify(data, null, 2)}`);
  } catch { showToast('Analyze failed'); }
};

// Footer time
setInterval(() => {
  const diff = Math.floor((Date.now() - startTime)/1000);
  const h = String(Math.floor(diff/3600)).padStart(2,'0');
  const m = String(Math.floor((diff%3600)/60)).padStart(2,'0');
  const s = String(diff%60).padStart(2,'0');
  const upEl = document.getElementById('uptime');
  if (upEl) upEl.textContent = `${h}:${m}:${s}`;
}, 1000);

// Init
connectWS();
loadLearnings();
setTimeout(() => {
  fetch('/api/status').then(r=>r.json()).then(s=>{
    if (s.model) {
      currentModel = s.model;
      modelPill.textContent = s.model + (s.ollama_connected ? ' • online' : ' • offline');
      modelSelect.value = s.model;
      setStatus(s.ollama_connected, s.ollama_connected ? 'online' : 'ollama offline');
    }
  }).catch(()=> setStatus(false, 'cannot reach server'));
}, 800);

// Keyboard shortcut to open drawer: Cmd+K / Ctrl+K
document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault();
    if (drawer.classList.contains('open')) closeDrawer(); else openDrawer();
  }
  if (e.key === 'Escape' && drawer.classList.contains('open')) closeDrawer();
});
