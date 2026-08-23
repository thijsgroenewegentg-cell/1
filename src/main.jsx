import React, { useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity, ArrowRight, Bell, Bot, Box, BriefcaseBusiness, Check,
  CheckCircle2, ChevronDown, CircleDollarSign, Clock3, Command, Cpu,
  Gauge, LayoutDashboard, Menu, MoreHorizontal, Network, Pause, Play,
  Plus, Search, Settings, Sparkles, Target, TrendingUp, Users, Workflow,
  X, Zap
} from 'lucide-react';
import './styles.css';

const agents = [
  { id: 1, name: 'Atlas', role: 'Lead Strategist', status: 'Working', color: '#ff9b61', initials: 'AT', task: 'Market opportunity scan', progress: 76, earned: 1280 },
  { id: 2, name: 'Nova', role: 'Content Operator', status: 'Working', color: '#b8ed79', initials: 'NO', task: 'Drafting outbound sequence', progress: 42, earned: 840 },
  { id: 3, name: 'Scout', role: 'Lead Researcher', status: 'Working', color: '#85c5ff', initials: 'SC', task: 'Qualifying 120 prospects', progress: 88, earned: 2250 },
  { id: 4, name: 'Echo', role: 'Sales Assistant', status: 'Idle', color: '#d8a5ff', initials: 'EC', task: 'Waiting for assignment', progress: 0, earned: 1670 },
];

const initialMissions = [
  { id: 1, title: 'Find & qualify 500 SaaS leads', label: 'LEAD GEN', agents: ['SC', 'AT'], progress: 68, value: '$4,200', due: '2d 14h', status: 'live' },
  { id: 2, title: 'Launch weekly insight newsletter', label: 'CONTENT', agents: ['NO', 'EC'], progress: 34, value: '$1,850', due: '4d 08h', status: 'live' },
  { id: 3, title: 'Re-engage dormant pipeline', label: 'SALES', agents: ['EC', 'SC'], progress: 91, value: '$7,500', due: '18h', status: 'live' },
];

const activity = [
  { icon: Check, text: <><b>Scout</b> qualified 24 new leads</>, time: '2m', tone: 'green' },
  { icon: CircleDollarSign, text: <>New deal attributed to <b>Echo</b></>, time: '18m', tone: 'orange' },
  { icon: Sparkles, text: <><b>Nova</b> completed 12 email drafts</>, time: '41m', tone: 'violet' },
  { icon: Activity, text: <><b>Atlas</b> updated market brief</>, time: '1h', tone: 'blue' },
];

function Logo() {
  return <div className="logo"><span className="logo-mark"><span/><span/><span/></span><span>HIVE</span></div>;
}

function Avatar({ initials, color, size = 'md' }) {
  return <div className={`avatar ${size}`} style={{ '--avatar': color || '#b8ed79' }}>{initials}</div>;
}

function Sidebar({ open, setOpen, active, setActive }) {
  const nav = [
    ['Overview', LayoutDashboard], ['My army', Users], ['Missions', Target],
    ['Workflows', Workflow], ['Earnings', TrendingUp],
  ];
  return <aside className={`sidebar ${open ? 'open' : ''}`}>
    <div className="side-top"><Logo/><button className="mobile-close" onClick={() => setOpen(false)}><X size={20}/></button></div>
    <div className="workspace"><div className="workspace-icon">TH</div><div><small>WORKSPACE</small><strong>Thijs HQ</strong></div><ChevronDown size={15}/></div>
    <nav>
      <div className="nav-label">COMMAND CENTER</div>
      {nav.map(([name, Icon]) => <button key={name} className={active === name ? 'active' : ''} onClick={() => { setActive(name); setOpen(false); }}><Icon size={18}/><span>{name}</span>{name === 'Missions' && <em>3</em>}</button>)}
      <div className="nav-label second">SYSTEM</div>
      <button onClick={() => setActive('Integrations')}><Box size={18}/><span>Integrations</span></button>
      <button onClick={() => setActive('Settings')}><Settings size={18}/><span>Settings</span></button>
    </nav>
    <div className="plan-card"><div className="plan-head"><Zap size={15}/><span>PRO PLAN</span></div><strong>7,840 <small>/ 10k credits</small></strong><div className="credit-bar"><i/></div><button>Manage plan <ArrowRight size={14}/></button></div>
    <div className="profile"><Avatar initials="TG" color="#f3c969"/><div><strong>Thijs Groenewegen</strong><small>Owner</small></div><MoreHorizontal size={18}/></div>
  </aside>
}

function Header({ setOpen, setModal }) {
  return <header>
    <button className="menu" onClick={() => setOpen(true)}><Menu size={22}/></button>
    <div className="search"><Search size={17}/><input placeholder="Search agents, missions..."/><kbd>⌘ K</kbd></div>
    <div className="header-actions"><button className="icon-btn"><Bell size={19}/><i/></button><button className="launch" onClick={() => setModal(true)}><Plus size={17}/> New mission</button></div>
  </header>
}

function StatCard({ label, value, detail, icon: Icon, accent, children }) {
  return <div className="stat-card card"><div className="stat-top"><span>{label}</span><div className="stat-icon" style={{'--accent': accent}}><Icon size={18}/></div></div><div className="stat-value">{value}</div><div className="stat-detail">{detail}</div>{children}</div>
}

function RevenueChart() {
  const values = [18, 27, 23, 38, 35, 52, 47, 70, 64, 81, 88, 92];
  const points = values.map((v, i) => `${(i / 11) * 100},${100-v}`).join(' ');
  return <div className="chart-card card">
    <div className="card-heading"><div><span className="eyebrow">REVENUE GENERATED</span><div className="revenue-line"><strong>$12,460</strong><span><TrendingUp size={13}/> 18.4%</span></div></div><select defaultValue="30"><option value="30">Last 30 days</option><option value="7">Last 7 days</option></select></div>
    <div className="chart-wrap"><div className="y-labels"><span>$4k</span><span>$3k</span><span>$2k</span><span>$1k</span><span>$0</span></div><div className="plot"><div className="grid-lines"><i/><i/><i/><i/><i/></div><svg viewBox="0 0 100 100" preserveAspectRatio="none"><defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#b8ed79" stopOpacity=".27"/><stop offset="100%" stopColor="#b8ed79" stopOpacity="0"/></linearGradient></defs><polygon points={`0,100 ${points} 100,100`} fill="url(#area)"/><polyline points={points} fill="none" stroke="#b8ed79" strokeWidth="1.7" vectorEffect="non-scaling-stroke"/></svg><div className="x-labels"><span>Jul 24</span><span>Jul 30</span><span>Aug 5</span><span>Aug 11</span><span>Aug 17</span><span>Aug 23</span></div></div></div>
  </div>
}

function MissionRow({ mission, onPause }) {
  return <div className="mission-row"><div className="mission-main"><div className="mission-icon"><Target size={18}/></div><div><strong>{mission.title}</strong><span className="tag">{mission.label}</span></div></div><div className="agent-stack">{mission.agents.map((a, i) => <Avatar key={a} initials={a} color={['#85c5ff','#ff9b61','#b8ed79','#d8a5ff'][(i+mission.id)%4]} size="sm"/>)}</div><div className="mission-progress"><div><span>{mission.status === 'paused' ? 'Paused' : `${mission.progress}% complete`}</span><b>{mission.value}</b></div><div className="progress"><i style={{width: `${mission.progress}%`}}/></div></div><div className="due"><Clock3 size={14}/>{mission.due}</div><button className="row-menu" onClick={() => onPause(mission.id)} title={mission.status === 'paused' ? 'Resume' : 'Pause'}>{mission.status === 'paused' ? <Play size={16}/> : <Pause size={16}/>}</button></div>
}

function AgentCard({ agent }) {
  return <div className="agent-card"><div className="agent-top"><Avatar initials={agent.initials} color={agent.color}/><div className="agent-info"><strong>{agent.name}</strong><span>{agent.role}</span></div><span className={`status ${agent.status.toLowerCase()}`}><i/>{agent.status}</span></div><div className="agent-task"><div><span>{agent.task}</span><b>{agent.progress}%</b></div><div className="progress"><i style={{width: `${agent.progress}%`, background: agent.color}}/></div></div><div className="agent-bottom"><span>Generated</span><strong>${agent.earned.toLocaleString()}</strong><button><ArrowRight size={15}/></button></div></div>
}

function Modal({ close, addMission }) {
  const [title, setTitle] = useState('');
  const [goal, setGoal] = useState('Lead generation');
  const submit = e => { e.preventDefault(); if (!title.trim()) return; addMission(title, goal); close(); };
  return <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && close()}><div className="modal"><div className="modal-head"><div><span className="eyebrow">DEPLOY THE ARMY</span><h2>Launch a mission</h2></div><button onClick={close}><X size={20}/></button></div><p>Give your agents a clear outcome. Hive will assemble the best team and break it into tasks.</p><form onSubmit={submit}><label>Mission outcome<input autoFocus value={title} onChange={e => setTitle(e.target.value)} placeholder="e.g. Book 20 qualified sales calls"/></label><label>Primary playbook<select value={goal} onChange={e => setGoal(e.target.value)}><option>Lead generation</option><option>Content engine</option><option>Sales pipeline</option><option>Market research</option></select></label><div className="assign-preview"><div className="spark"><Sparkles size={18}/></div><div><strong>Automatic team assignment</strong><span>Atlas will plan the mission and recruit specialist agents.</span></div><div className="agent-stack"><Avatar initials="AT" color="#ff9b61" size="sm"/><Avatar initials="SC" color="#85c5ff" size="sm"/></div></div><div className="modal-actions"><button type="button" className="cancel" onClick={close}>Cancel</button><button className="launch" type="submit">Launch mission <ArrowRight size={16}/></button></div></form></div></div>
}

function Dashboard() {
  const [sideOpen, setSideOpen] = useState(false);
  const [active, setActive] = useState('Overview');
  const [modal, setModal] = useState(false);
  const [missions, setMissions] = useState(initialMissions);
  const working = agents.filter(a => a.status === 'Working').length;
  const addMission = (title, goal) => setMissions(prev => [...prev, { id: Date.now(), title, label: goal.toUpperCase().split(' ')[0], agents: ['AT','SC'], progress: 2, value: '$0', due: '7d 00h', status: 'live' }]);
  const togglePause = id => setMissions(ms => ms.map(m => m.id === id ? {...m, status: m.status === 'paused' ? 'live' : 'paused'} : m));
  return <div className="app"><Sidebar open={sideOpen} setOpen={setSideOpen} active={active} setActive={setActive}/>{sideOpen && <div className="side-scrim" onClick={() => setSideOpen(false)}/>}<main><Header setOpen={setSideOpen} setModal={setModal}/><div className="content">
    <div className="welcome"><div><span className="eyebrow"><i/> LIVE COMMAND CENTER</span><h1>Good morning, Thijs.</h1><p>Your army is working. Here’s what they’ve accomplished.</p></div><div className="system-live"><span><i/> ALL SYSTEMS OPERATIONAL</span><b>4 agents online</b></div></div>
    <section className="stats"><StatCard label="TOTAL GENERATED" value="$12,460" detail={<><span className="up">↗ 18.4%</span> vs last month</>} icon={CircleDollarSign} accent="#b8ed79"/><StatCard label="ACTIVE AGENTS" value={`${working} / 4`} detail="1 agent standing by" icon={Bot} accent="#85c5ff"><div className="micro-bars"><i/><i/><i/><i className="muted"/></div></StatCard><StatCard label="TASKS COMPLETED" value="1,284" detail={<><span className="up">↗ 142</span> this week</>} icon={CheckCircle2} accent="#d8a5ff"/><StatCard label="AVG. ROI" value="8.4×" detail="Across all missions" icon={Gauge} accent="#ff9b61"/></section>
    <section className="top-grid"><RevenueChart/><div className="activity-card card"><div className="card-heading"><span className="eyebrow">LIVE ACTIVITY</span><button>View all</button></div><div className="activity-list">{activity.map((a,i) => <div className="activity-item" key={i}><div className={`activity-icon ${a.tone}`}><a.icon size={15}/></div><div><span>{a.text}</span><small>{a.time} ago</small></div></div>)}</div><div className="pulse-line"><i/><span>Agents are working now</span><div><b/><b/><b/></div></div></div></section>
    <section className="section-block"><div className="section-title"><div><span className="eyebrow">MISSION CONTROL</span><h2>Active missions</h2></div><button className="text-button" onClick={() => setModal(true)}>New mission <Plus size={15}/></button></div><div className="missions card">{missions.map(m => <MissionRow key={m.id} mission={m} onPause={togglePause}/>)}</div></section>
    <section className="section-block"><div className="section-title"><div><span className="eyebrow">YOUR WORKFORCE</span><h2>Meet the army</h2></div><button className="text-button">Manage agents <ArrowRight size={15}/></button></div><div className="agents-grid">{agents.map(a => <AgentCard key={a.id} agent={a}/>)}</div></section>
    <div className="principle"><Command size={17}/><span>Your agents create leverage, not magic. Every mission stays under your control.</span></div>
  </div></main>{modal && <Modal close={() => setModal(false)} addMission={addMission}/>}</div>;
}

createRoot(document.getElementById('root')).render(<Dashboard/>);
