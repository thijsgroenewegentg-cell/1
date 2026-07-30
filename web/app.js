const chatEl = document.getElementById('chat');
const inputEl = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const modelSelect = document.getElementById('model-select');
const bootStatusEl = document.getElementById('boot-status');

let ws = null;
let currentModel = 'jarvis';
let messageCount = 0;
let startTime = Date.now();
let voiceEnabled = false;
let synth = window.speechSynthesis;

function connectWS() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${location.host}/ws`;
  console.log('Connecting to', wsUrl);
  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    console.log('WS connected');
    updateStatus('online', 'Connected');
    bootStatusEl.textContent = '✓ Connected';
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleWSMessage(data);
    } catch(e) {
      console.error(e);
    }
  };

  ws.onclose = () => {
    console.log('WS closed');
    updateStatus('offline', 'Disconnected - Reconnecting...');
    setTimeout(connectWS, 2000);
  };

  ws.onerror = (err) => {
    console.error('WS error', err);
    updateStatus('offline', 'Connection error');
  };
}

function handleWSMessage(msg) {
  const { type, data } = msg;
  switch(type) {
    case 'status':
      document.getElementById('model-name').textContent = data.model || currentModel;
      document.getElementById('ollama-status').textContent = data.ollama_connected ? 'Ollama ✓' : 'Ollama ✗';
      document.getElementById('memory-count').textContent = data.memory_count || 0;
      document.getElementById('stat-model').textContent = data.model;
      currentModel = data.model;
      break;
    case 'message':
      addMessage('jarvis', data);
      speakIfEnabled(data);
      hideThinking();
      break;
    case 'stream':
      appendToLastJarvisMessage(data);
      break;
    case 'tool':
      addMessage('tool', data, 'TOOL');
      break;
    case 'thinking':
      showThinking();
      break;
    case 'done':
      hideThinking();
      messageCount++;
      document.getElementById('stat-tokens').textContent = data.length;
      break;
    case 'clear':
      chatEl.innerHTML = '';
      break;
    case 'error':
      addMessage('system', 'Error: ' + data);
      hideThinking();
      break;
  }
}

// UI Helpers
function addMessage(role, text, label) {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  const now = new Date().toLocaleTimeString();
  const avatarText = role === 'user' ? 'YOU' : role === 'jarvis' ? 'JAR' : role === 'tool' ? '🔧' : 'SYS';
  const metaLabel = label || (role === 'user' ? `YOU • ${now}` : role === 'jarvis' ? `J.A.R.V.I.S • ${now} • ${currentModel}` : `SYSTEM • ${now}`);

  div.innerHTML = `
    <div class="avatar">${avatarText}</div>
    <div class="content">
      <div class="meta">${metaLabel}</div>
      <div class="text"></div>
    </div>
  `;
  const textEl = div.querySelector('.text');
  // Basic markdown-like rendering
  textEl.innerHTML = formatText(text);
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
  return div;
}

let lastJarvisDiv = null;
function appendToLastJarvisMessage(chunk) {
  if (!lastJarvisDiv || !lastJarvisDiv.classList.contains('jarvis') || lastJarvisDiv.dataset.done === "true") {
    lastJarvisDiv = addMessage('jarvis', '', 'J.A.R.V.I.S • Streaming...');
    lastJarvisDiv.dataset.streaming = "true";
  }
  const textEl = lastJarvisDiv.querySelector('.text');
  // Append raw then format incrementally? simple append
  textEl.textContent += chunk;
  chatEl.scrollTop = chatEl.scrollHeight;
}

function formatText(t) {
  // Escape HTML
  let escaped = t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  // Code blocks
  escaped = escaped.replace(/```([\s\S]*?)```/g, '<pre style="background:#000;padding:8px;border-radius:4px;overflow:auto;margin:8px 0"><code>$1</code></pre>');
  // Bold
  escaped = escaped.replace(/\*\*(.*?)\*\*/g, '<strong style="color:var(--cyan)">$1</strong>');
  // Line breaks
  escaped = escaped.replace(/\n/g, '<br>');
  return escaped;
}

let thinkingEl = null;
function showThinking() {
  hideThinking();
  thinkingEl = addMessage('system', '<div class="thinking"><span>JARVIS is processing</span><span class="thinking-dots"><span>.</span><span>.</span><span>.</span></span></div>', 'NEURAL LINK');
  document.getElementById('model-name').textContent = currentModel + ' • Thinking...';
  const dot = document.querySelector('.dot');
  if(dot) dot.className = 'dot busy';
}

function hideThinking() {
  if(thinkingEl) {
    thinkingEl.remove();
    thinkingEl = null;
  }
  const dot = document.querySelector('.dot');
  if(dot) dot.className = 'dot online';
}

function updateStatus(state, text) {
  const ollamaEl = document.getElementById('ollama-status');
  ollamaEl.textContent = text;
  const dot = document.querySelector('.status-panel .dot');
  if(dot) {
    dot.className = state === 'online' ? 'dot online' : 'dot';
  }
}

// Send
function sendMessage() {
  const text = inputEl.value.trim();
  if(!text || !ws || ws.readyState !== WebSocket.OPEN) return;
  
  addMessage('user', text);
  ws.send(JSON.stringify({ message: text, model: currentModel }));
  inputEl.value = '';
  inputEl.focus();
  
  // Waveform effect
  triggerWaveform();
}

sendBtn.onclick = sendMessage;
inputEl.addEventListener('keydown', e => {
  if(e.key === 'Enter') sendMessage();
});

function quick(text) {
  inputEl.value = text;
  sendMessage();
}

function clearChat() {
  if(ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ message: '/clear' }));
  }
  chatEl.innerHTML = '';
}

function changeModel() {
  currentModel = modelSelect.value;
  document.getElementById('model-name').textContent = currentModel;
  addMessage('system', `Model switched to ${currentModel}, Sir.`);
}

function toggleVoice() {
  voiceEnabled = !voiceEnabled;
  document.getElementById('voice-btn').textContent = `VOICE: ${voiceEnabled ? 'ON' : 'OFF'}`;
  document.getElementById('voice-status').textContent = voiceEnabled ? 'browser TTS' : 'offline';
  if(voiceEnabled) {
    addMessage('system', 'Voice enabled, Sir. Using browser synthesis.');
  }
}

function speakIfEnabled(text) {
  if(!voiceEnabled || !synth) return;
  // Clean text
  let clean = text.replace(/```[\s\S]*?```/g, '').replace(/\*\*/g, '').replace(/\[.*?\]/g, '').slice(0, 500);
  let utter = new SpeechSynthesisUtterance(clean);
  // Try to find British male voice
  let voices = synth.getVoices();
  let british = voices.find(v => v.name.includes('Google UK English Male') || v.name.includes('Ryan') || v.lang === 'en-GB');
  if(british) utter.voice = british;
  utter.rate = 0.95;
  utter.pitch = 0.9;
  synth.speak(utter);
}

// Waveform
const canvas = document.getElementById('waveform');
const ctx = canvas.getContext('2d');
let waveformActive = false;
let waveformTime = 0;

function drawWaveform() {
  ctx.clearRect(0,0,canvas.width,canvas.height);
  ctx.strokeStyle = waveformActive ? '#00d4ff' : '#1c2a3a';
  ctx.lineWidth = 2;
  ctx.beginPath();
  for(let x=0; x<canvas.width; x++) {
    let y = canvas.height/2;
    if(waveformActive) {
      y += Math.sin((x + waveformTime)/10) * 20 * Math.sin(waveformTime/20) + (Math.random()-0.5)*5;
    } else {
      y += Math.sin((x+waveformTime)/30) * 2;
    }
    if(x===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
  }
  ctx.stroke();
  waveformTime++;
  if(waveformActive && waveformTime > 100) {
    waveformActive = false;
    waveformTime = 0;
  }
  requestAnimationFrame(drawWaveform);
}
function triggerWaveform() {
  waveformActive = true;
  waveformTime = 0;
}
drawWaveform();

// Clock & uptime
setInterval(() => {
  document.getElementById('footer-time').textContent = new Date().toLocaleString();
  let diff = Math.floor((Date.now()-startTime)/1000);
  let h = String(Math.floor(diff/3600)).padStart(2,'0');
  let m = String(Math.floor((diff%3600)/60)).padStart(2,'0');
  let s = String(diff%60).padStart(2,'0');
  document.getElementById('uptime').textContent = `${h}:${m}:${s}`;
  document.getElementById('stat-latency').textContent = Math.floor(Math.random()*40+20)+'ms';
}, 1000);

// Memories
async function loadMemories() {
  try {
    let resp = await fetch('/api/memories');
    let data = await resp.json();
    let list = document.getElementById('memory-list');
    if(!data.memories || data.memories.length===0) {
      list.innerHTML = '<div style="opacity:0.5">No memories yet</div>';
      return;
    }
    list.innerHTML = data.memories.slice(-10).reverse().map(m => 
      `<div class="memory-item"><strong>${m.key}</strong>: ${m.value.slice(0,80)}</div>`
    ).join('');
  } catch(e) {
    console.error(e);
  }
}

// Init
connectWS();
loadMemories();
setTimeout(() => synth.getVoices(), 500);

// Random boot status
setTimeout(() => {
  fetch('/api/status').then(r=>r.json()).then(s => {
    document.getElementById('model-name').textContent = s.model || 'jarvis';
    document.getElementById('ollama-status').textContent = s.ollama_connected ? 'Ollama ✓' : 'Ollama ✗ Connect';
    document.getElementById('memory-count').textContent = s.memory_count || 0;
    bootStatusEl.textContent = s.ollama_connected ? '✓ Online' : '✗ Offline - run ollama serve';
  }).catch(() => {
    bootStatusEl.textContent = '✗ Cannot reach ' + location.host;
  });
}, 1000);
