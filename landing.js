/* =========================================================
   VoiceOS landing — interactions + EN/NL site translations
   Structure mirrors the reference site's flow; all copy is ours.
   ========================================================= */

/* ---------- site strings ---------- */
const SITE = {
  en: {
    navFeatures: 'Features', navActions: 'Actions', navPrivacy: 'Privacy', navLove: 'Love',
    navCta: 'Launch live demo', langToggle: '🇳🇱 NL', langToggleFoot: '🇳🇱 Nederlands',
    ycBadge: 'Open source · MIT · 100% free',
    heroTitle: 'Voice assistant<br /><span class="grad">at your fingertips</span>',
    heroSub: 'Say it once, let it go. VoiceOS turns spoken intent into finished work — across email, calendar, messages, files and tasks.',
    heroCta1: '▶ Try the live demo', heroCta2: 'Download — Windows & Linux',
    pointTitle: 'Point anywhere on your screen.',
    pointSub: 'Your cursor is the context. No more explaining — just point and ask.',
    pointQuote: '“can you find his LinkedIn”',
    prodTitle: 'Not just another dictation app',
    prodSub: 'Dictation only speeds up your typing. VoiceOS multiplies your productivity.',
    pTyping: 'Typing', pDictation: 'Dictation',
    prodNote: '⇧ your productivity — one command instead of ten clicks.',
    actStrike: 'Speech-to-text', actTitle: 'Voice-to-action',
    actSub: 'Send the email, file the ticket, schedule the meeting. Say it once — VoiceOS does it in the right app.',
    a1: 'Send an email', a2: 'Reply to Maya', a3: 'Schedule a meeting', a4: 'Find that PDF',
    a5: 'Take a note', a6: 'Text Mom', a7: 'File a bug', a8: 'Search the web',
    a9: 'Open the roadmap', a10: 'Draft a proposal', a11: 'Add a daily note',
    searchTitleA: 'Stop looking 👀 for',
    searchSub: 'You know exactly what you’re looking for. You just don’t know where it is. Ask, and VoiceOS pulls it up in seconds.',
    searchQuote: '“search for last year’s tax returns”',
    agentTitle: 'Agent keeps you 🤝 on task.',
    agentSub: 'Say it once and let it go. VoiceOS tracks the task and brings it back at the right time — so nothing sits in your head.',
    agentQuote: '“remind me to send Maya the deck”',
    privBadge: 'Privacy',
    privTitle: 'What you say stays yours',
    privSub: 'Your audio is never stored on our servers and never used to train models. You decide what leaves your device.',
    privOnDevice: 'On your device', privSharing: 'Optional sharing',
    privT1: 'Save transcripts on this device', privT2: 'Don’t save audio in the cloud',
    privT3: 'Never use my dictation to train AI models',
    privT4: 'Send anonymous diagnostics and crash reports',
    privT4n: 'Never includes raw audio or full transcripts tied to you.',
    loveTitle: 'Wall of Love',
    loveSub: 'Founders, creators, and builders are replacing typing with VoiceOS.',
    q1: '“I answered 12 mails walking the dog. This is the future of the desktop.”',
    q2: '“The confirmation cards are genius. It acts fast but never oversteps.”',
    q3: '“Dutch commands just work. “Plan een vergadering met Lisa” — done.”',
    q1n: 'G. Pereira', q1r: 'Founder', q2n: 'S. Bakker', q2r: 'Product lead', q3n: 'J. van Dijk', q3r: 'Indie maker',
    loveCta: 'Say it once — try it now',
    footTag: 'say it once, let it go.', footDemo: 'Live demo',
  },
  nl: {
    navFeatures: 'Functies', navActions: 'Acties', navPrivacy: 'Privacy', navLove: 'Liefde',
    navCta: 'Start live demo', langToggle: '🇬🇧 EN', langToggleFoot: '🇬🇧 English',
    ycBadge: 'Open source · MIT · 100% gratis',
    heroTitle: 'Spraakassistent<br /><span class="grad">binnen handbereik</span>',
    heroSub: 'Zeg het één keer, en het is geregeld. VoiceOS zet gesproken intentie om in afgerond werk — in e-mail, agenda, berichten, bestanden en taken.',
    heroCta1: '▶ Probeer de live demo', heroCta2: 'Download — Windows & Linux',
    pointTitle: 'Wijs naar iets op je scherm.',
    pointSub: 'Je cursor is de context. Niet meer uitleggen — gewoon wijzen en vragen.',
    pointQuote: '“kun jij zijn LinkedIn vinden”',
    prodTitle: 'Niet zomaar een dicteer-app',
    prodSub: 'Dicteren versnelt alleen je typen. VoiceOS vermenigvuldigt je productiviteit.',
    pTyping: 'Typen', pDictation: 'Dicteren',
    prodNote: '⇧ je productiviteit — één opdracht in plaats van tien klikken.',
    actStrike: 'Spraak-naar-tekst', actTitle: 'Spraak-naar-actie',
    actSub: 'Verstuur de e-mail, maak het ticket aan, plan de vergadering. Zeg het één keer — VoiceOS doet het in de juiste app.',
    a1: 'Stuur een e-mail', a2: 'Beantwoord Maya', a3: 'Plan een vergadering', a4: 'Zoek die pdf',
    a5: 'Maak een notitie', a6: 'App mam', a7: 'Meld een bug', a8: 'Zoek op internet',
    a9: 'Open de routekaart', a10: 'Stel een voorstel op', a11: 'Voeg een dagnnotitie toe',
    searchTitleA: 'Stop met zoeken 👀 naar',
    searchSub: 'Je weet precies wat je zoekt. Je weet alleen niet waar het staat. Vraag het — VoiceOS tovert het binnen seconden tevoorschijn.',
    searchQuote: '“zoek de belastingaangifte van vorig jaar”',
    agentTitle: 'De agent houdt je 🤝 op koers.',
    agentSub: 'Zeg het één keer en laat los. VoiceOS bewaakt de taak en brengt hem terug op het juiste moment — niets blijft in je hoofd hangen.',
    agentQuote: '“herinner me eraan Maya de presentatie te sturen”',
    privBadge: 'Privacy',
    privTitle: 'Wat je zegt blijft van jou',
    privSub: 'Je audio wordt nooit op onze servers opgeslagen en nooit gebruikt om modellen te trainen. Jij bepaalt wat je apparaat verlaat.',
    privOnDevice: 'Op je apparaat', privSharing: 'Optioneel delen',
    privT1: 'Bewaar transcripties op dit apparaat', privT2: 'Bewaar geen audio in de cloud',
    privT3: 'Gebruik mijn dictaat nooit om AI-modellen te trainen',
    privT4: 'Stuur anonieme diagnostiek en crashrapporten',
    privT4n: 'Bevat nooit ruwe audio of volledige transcripties die aan jou gekoppeld zijn.',
    loveTitle: 'Wall of Love',
    loveSub: 'Oprichters, makers en bouwers vervangen typen door VoiceOS.',
    q1: '“Ik beantwoordde 12 mails terwijl ik de hond uitliet. Dit is de toekomst van de desktop.”',
    q2: '“De bevestigingskaarten zijn geniaal. Snel, maar gaat nooit te ver.”',
    q3: '“Nederlandse commando’s werken gewoon. “Plan een vergadering met Lisa” — klaar.”',
    q1n: 'G. Pereira', q1r: 'Oprichter', q2n: 'S. Bakker', q2r: 'Productlead', q3n: 'J. van Dijk', q3r: 'Indie maker',
    loveCta: 'Zeg het één keer — probeer nu',
    footTag: 'zeg het één keer, en het is geregeld.', footDemo: 'Live demo',
  },
};

/* ---------- language handling ---------- */
const LANG_KEY = 'voiceos_site_lang';
function siteLang() {
  try {
    return localStorage.getItem(LANG_KEY)
      || (((navigator.language || 'en').toLowerCase().startsWith('nl')) ? 'nl' : 'en');
  } catch (_) { return 'en'; }
}
function setSiteLang(l) {
  try { localStorage.setItem(LANG_KEY, l); } catch (_) {}
  applySiteLang(l);
}
function applySiteLang(l) {
  const dict = SITE[l] || SITE.en;
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const k = el.getAttribute('data-i18n');
    if (dict[k] != null) el.textContent = dict[k];
  });
  document.querySelectorAll('[data-i18n-html]').forEach(el => {
    const k = el.getAttribute('data-i18n-html');
    if (dict[k] != null) el.innerHTML = dict[k];
  });
  const t1 = document.getElementById('langToggle');  if (t1) t1.textContent = dict.langToggle;
  const t2 = document.getElementById('langToggleFoot'); if (t2) t2.textContent = dict.langToggleFoot;
  document.getElementById('htmlRoot').setAttribute('lang', l);
  document.body.dataset.lang = l;
  ROTATOR_WORDS.length = 0;
  ROTATOR_WORDS.push(...(l === 'nl'
    ? ['dat bestand', 'die e-mail', 'dat document', 'die notitie']
    : ['that file', 'that email', 'that doc', 'that note']));
  window.currentSiteLang = l;
}

/* ---------- app-tile marquee (generic tiles — no copied brand assets) ---------- */
const TILE_ICONS = ['✉️','📆','💬','📝','📁','✅','🌐','🗺️','📊','🎧','⌨️','🎨','📄','🔐','🧠','⚡'];
function buildMarquee() {
  const track = document.getElementById('marqueeTrack');
  if (!track) return;
  const row = TILE_ICONS.concat(TILE_ICONS, TILE_ICONS); // 3× for seamless loop
  track.innerHTML = row.map(i => `<span class="tile">${i}</span>`).join('');
}

/* ---------- hero mini-demo (loops; text follows site language) ---------- */
const DEMOS = {
  en: [
    { tag: 'Agent mode · confirmation', title: 'Send email to John about the meeting',
      lines: [['To', 'john@company.com'], ['Subject', 'The Meeting']], actions: ['SEND', 'CANCEL'] },
    { tag: 'Workflow · 4 steps', title: 'Send John the latest project deck',
      lines: [['✓ Found', 'project_deck_v7.key'], ['◐ Compose', 'john@company.com'], ['○ Attach', 'waiting'], ['○ Send', 'waiting']], actions: ['RUN', 'CANCEL'] },
    { tag: 'Dictation mode', title: '“um so the onboarding uh tested well”',
      lines: [['Cleaned', 'The onboarding tested well.'], ['Typed into', 'Notes']], actions: ['DONE'] },
    { tag: 'Morning briefing', title: 'Your day at a glance',
      lines: [['Meeting', 'Design review · 2:00 PM'], ['Mail', '1 unread — Maya'], ['Tasks', '2 open']], actions: ['OK'] },
  ],
  nl: [
    { tag: 'Agentmodus · bevestiging', title: 'Stuur een e-mail naar John over de vergadering',
      lines: [['Aan', 'john@company.com'], ['Onderwerp', 'De vergadering']], actions: ['VERSTUUR', 'ANNULEREN'] },
    { tag: 'Workflow · 4 stappen', title: 'Stuur John de nieuwste projectpresentatie',
      lines: [['✓ Gevonden', 'project_deck_v7.key'], ['◐ Opstellen', 'john@company.com'], ['○ Bijvoegen', 'wacht'], ['○ Versturen', 'wacht']], actions: ['UITVOEREN', 'ANNULEREN'] },
    { tag: 'Dicteermodus', title: '“eh dus de onboarding testte zeg maar goed”',
      lines: [['Opgeschoond', 'De onboarding testte goed.'], ['Getypt in', 'Notities']], actions: ['KLAAR'] },
    { tag: 'Ochtendbriefing', title: 'Je dag in één oogopslag',
      lines: [['Afspraak', 'Designreview · 14:00'], ['Mail', '1 ongelezen — Maya'], ['Taken', '2 open']], actions: ['OKÉ'] },
  ],
};
const ROTATOR_WORDS = [];

const sleep = ms => new Promise(r => setTimeout(r, ms));
async function runDemo() {
  const tagEl = document.getElementById('demoTag'), titleEl = document.getElementById('demoTitle'),
        linesEl = document.getElementById('demoLines'), actionsEl = document.getElementById('demoActions');
  if (!tagEl) return;
  async function typeTitle(text) {
    for (let i = 0; i <= text.length; i++) {
      titleEl.innerHTML = text.slice(0, i).replace(/</g, '&lt;') + '<span class="caret"></span>';
      await sleep(30);
    }
    titleEl.textContent = text;
  }
  let i = 0;
  for (;;) {
    const lang = window.currentSiteLang || 'en';
    const scenes = DEMOS[lang] || DEMOS.en;
    const scene = scenes[i % scenes.length];
    tagEl.textContent = scene.tag;
    linesEl.innerHTML = ''; actionsEl.innerHTML = '';
    await typeTitle(scene.title);
    for (const [k, v] of scene.lines) {
      const dk = document.createElement('span'); dk.className = 'k'; dk.textContent = k;
      const dv = document.createElement('span'); dv.className = 'v'; dv.textContent = v;
      linesEl.append(dk, dv); await sleep(200);
    }
    for (const a of scene.actions) {
      const b = document.createElement('span');
      b.className = 'demo-btn' + ((a === 'SEND' || a === 'RUN' || a === 'VERSTUUR' || a === 'UITVOEREN') ? ' primary' : '');
      b.textContent = a; actionsEl.appendChild(b);
    }
    await sleep(2400); i++;
  }
}

/* ---------- "stop looking for ___" rotator ---------- */
function runRotator() {
  const el = document.getElementById('rotator');
  if (!el) return;
  let i = 0;
  setInterval(() => {
    if (!ROTATOR_WORDS.length) return;
    el.classList.add('swap-out');
    setTimeout(() => { el.textContent = ROTATOR_WORDS[++i % ROTATOR_WORDS.length]; el.classList.remove('swap-out'); }, 220);
  }, 2200);
}

/* ---------- productivity bars: fill on scroll into view ---------- */
function runBars() {
  const fills = document.querySelectorAll('.pbar-fill');
  if (!fills.length) return;
  const set = () => fills.forEach(f => { f.style.width = (f.dataset.x * 9) + '%'; });
  if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { set(); io.disconnect(); } }), { threshold: .3 });
    io.observe(fills[0].closest('.prod-bars'));
  } else set();
}

/* ---------- boot ---------- */
buildMarquee();
applySiteLang(siteLang());
document.getElementById('langToggle')?.addEventListener('click', () => setSiteLang((window.currentSiteLang || 'en') === 'en' ? 'nl' : 'en'));
document.getElementById('langToggleFoot')?.addEventListener('click', () => setSiteLang((window.currentSiteLang || 'en') === 'en' ? 'nl' : 'en'));
runDemo();
runRotator();
runBars();
