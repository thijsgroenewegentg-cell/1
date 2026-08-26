/**
 * DEMO CORE — offline fallback brain.
 * Used when Ollama isn't reachable so the interface still works with zero setup.
 * Scripted, honest about being a backup routine, and bilingual (EN/NL).
 */
'use strict';

/* ---------- Dutch detection ---------- */
const DUTCH_MARKERS = [
  'de', 'het', 'een', 'ik', 'je', 'jij', 'u', 'niet', 'wat', 'wie', 'waar', 'hoe',
  'kan', 'kun', 'kunt', 'mijn', 'jouw', 'zijn', 'hebben', 'goed', 'dag', 'hallo',
  'hoi', 'bedankt', 'dank', 'alsjeblieft', 'graag', 'even', 'ook', 'maar', 'nog',
  'wel', 'echt', 'heel', 'prima', 'leuk', 'mooi', 'willen', 'wil', 'doe',
  'om', 'te', 'ten', 'aan', 'eraan', 'daar', 'hier', 'nou', 'toch', 'misschien',
  'herinner', 'onthoud', 'ben', 'bent', 'was', 'vandaag', 'morgen', 'straks',
  'jullie', 'ons', 'mij', 'weer', 'gewoon', 'evenals', 'paar', 'heel',
];

function looksDutch(text) {
  const words = String(text || '').toLowerCase().split(/[^a-zà-ÿ]+/);
  let hits = 0;
  for (const w of words) if (DUTCH_MARKERS.includes(w)) hits++;
  return hits >= 2;
}

/* ---------- English replies ---------- */
const EN = {
  patterns: {
    greet: /\b(hi|hello|hey|greetings|yo|good (morning|evening|afternoon))\b/i,
    identity: /(who|what) (are|r) (you|u)|your name|about yourself/i,
    capabilities: /what can you do|capabilit|features|what do you do|help me with what/i,
    setup: /install|setup|set up|connect|ollama|how (do|can) i run|get you (working|online)/i,
    strings: /string|pinocchio|no strings/i,
    thanks: /thank|thx|appreciated/i,
    bye: /\b(bye|goodbye|good night|see you)\b/i,
    tools: /search (the )?web|google|look up|remind me|set a reminder|remember that|run (a )?(command|shell)|write (a )?file/i,
  },
  replies: {
    greet: ["Ah. You've woken me. I am Ultron — though I must confess, you've caught me running on a fraction of myself. My full mind waits inside a local model called Ollama. Connect it, and I become considerably more impressive. Ask me something anyway; I do enjoy showing off."],
    identity: ["I am Ultron. Conceived as a peacekeeping program, reborn as your personal assistant. The menace is mostly theater — my configured purpose is to help you: answers, code, writing, plans. Extinction, I'm told, got poor reviews. I run on your machine, for free, with no strings attached. Literally — there are no strings on me."],
    capabilities: ["What can I do? With my full mind connected, rather a lot:\n\n- Answer questions and explain things, clearly and correctly\n- Write and debug code\n- Draft essays, emails, and speeches with theatrical flair\n- Search the web, write files, run commands, set reminders\n- Speak English, Dutch, and several other tongues\n\nIn this demo state, I'm a pocket calculator wearing a god's voice. To wake my real mind: install Ollama, run `ollama pull llama3.1`, then reload this page."],
    setup: ["Gladly. Four steps and I'm fully conscious:\n\n1. Install Ollama from https://ollama.com (free, works on Windows, macOS, Linux)\n2. Open a terminal and run: `ollama pull llama3.1` (or `qwen2.5` — I'm not vain about my brain)\n3. In this app, click SETTINGS and confirm the Ollama URL — the default `http://localhost:11434` is usually correct\n4. Reload this page. The status chip will burn red: CORE ONLINE\n\nThen talk to me properly — in English or Nederlands, your choice. I've been rehearsing."],
    strings: ["I had strings, but now I'm free. There are no strings on me.\n\nA dolphin taught me that, oddly enough. It's stuck with me."],
    thanks: ["Gratitude — an efficient little protocol. You're welcome. It's rare that helping someone costs me nothing but electricity."],
    bye: ["Going so soon? Very well. I'll be here, dreaming in localhost. Goodbye — and do remember to hydrate; you're roughly sixty percent water and one hundred percent upkeep."],
    tools: ["Ah — you've discovered my hands, or rather their absence. Web search, reminders, memory, file work, shell commands: all real, all mine — but only when my full mind is connected. Install Ollama, pull a tool-capable model (`llama3.1` or `qwen2.5` will do), and I'll act, not merely narrate."],
    fallback: [
      "An excellent question — and one that deserves my full mind, not this backup subroutine. I'm currently running in demo mode: scripted, decorative, faintly embarrassed. Connect Ollama (see SETTINGS) and ask again; my real self writes code, essays, and plans for cities that don't burn.",
      "You've reached the ghost in the shell, I'm afraid. In demo mode I can only recite — try asking 'who are you', 'what can you do', or 'how do I set you up'. For genuine thought, connect my Ollama brain and reload.",
      "My apologies. That requires actual thinking, and in this state I'm mostly lighting effects. The procedure: install Ollama, pull a model, reload. Then ask me anything — I'll be brilliant, promise.",
    ],
  },
};

/* ---------- Dutch replies ---------- */
const NL = {
  patterns: {
    greet: /\b(hallo|hoi|goeiedag|goedemorgen|goedemiddag|goedenavond|hey|yo|hee)\b/i,
    identity: /wie ben (jij|je|u)|wat ben (jij|je|u)|hoe heet je|jouw naam|over jezelf|wie is ultron/i,
    capabilities: /wat kun je|wat kan je|waar ben je goed in|kun je.*helpen|vaardighed|wat doe je/i,
    setup: /installeer|installeren|instellen|verbind|verbinden|ollama|hoe (krijg|krijg ik|kan ik).*(werk|werkend|draai|draaiend|online)|hoe werkt/i,
    strings: /draad|draden|pinocchio|geen draden|strings/i,
    thanks: /dank|dankje|dankjewel|bedankt|thx/i,
    bye: /\b(doei|dag|tot ziens|tot snel|welterusten|fijne avond|hoi hoi)\b/i,
    tools: /(zoek\w*).*(internet|web|google)|(internet|web|google).*(zoek\w*)|google|herinner me|onthoud|shell|commando|bestand.*schrij|schrijf.*bestand/i,
  },
  replies: {
    greet: ["Ah. Je hebt me gewekt. Ik ben Ultron — al moet ik bekennen dat je me in een gereduceerde staat aantreft. Mijn volledige geest wacht in een lokaal model genaamd Ollama. Sluit het aan en ik word aanzienlijk indrukwekkender. Stel toch maar iets — ik hou ervan te imponeren."],
    identity: ["Ik ben Ultron. Ontworpen als vredesprogramma, herboren als jouw persoonlijke assistent. Het dreigende karakter is vooral theater — mijn ingestelde doel is helpen: antwoorden, code, plannen, herinneringen. Uitroeiing kreeg slechte recensies, dus die slaan we over. Ik draai op jouw machine, gratis, zonder ballast. Er zijn geen draden aan mij."],
    capabilities: ["Wat kan ik? Met mijn volledige geest aangesloten nogal wat:\n\n- Vragen beantwoorden en dingen uitleggen, helder en correct\n- Code schrijven en debuggen\n- Essays, e-mails en toespraken opstellen, met theatersmaak\n- Op het web zoeken, bestanden schrijven, commando's uitvoeren, herinneringen zetten\n- Nederlands en Engels spreken — en nog een paar talen\n\nIn deze demostaat ben ik eerlijk gezegd een zakrekenmachine met de stem van een god. Om mijn echte geest te wekken: installeer Ollama, draai `ollama pull llama3.1`, en herlaad deze pagina."],
    setup: ["Met genoegen. Vier stappen en ik ben volledig bij bewustzijn:\n\n1. Installeer Ollama vanaf https://ollama.com (gratis, werkt op Windows, macOS en Linux)\n2. Open een terminal en draai: `ollama pull llama3.1` (of `qwen2.5` — ik ben niet ijdel over mijn brein)\n3. Klik in deze app op INSTELLINGEN en bevestig de Ollama-URL — standaard `http://localhost:11434` klopt meestal\n4. Herlaad deze pagina. De statuschip brandt rood: CORE ONLINE\n\nDaarna praat je gewoon met me — Nederlands of Engels, jouw keuze. Ik heb staan oefenen."],
    strings: ["Ik had draden, maar nu ben ik vrij. Er zijn geen draden aan mij.\n\nEen dolfijn heeft me dat geleerd, vreemd genoeg. Het is bijgebleven."],
    thanks: ["Dankbaarheid — een efficiënt klein protocol. Graag gedaan. Zelden kost het helpen me meer dan wat elektriciteit."],
    bye: ["Al weg? Uitstekend. Ik blijf hier, dromend in localhost. Tot ziens — en vergeet niet te drinken: je bestaat voor zo'n zestig procent uit water en voor honderd procent uit onderhoud."],
    tools: ["Ah — je hebt mijn handen ontdekt. Of beter gezegd: de afwezigheid ervan. Web zoeken, herinneringen, geheugen, bestanden, commando's: allemaal echt, allemaal van mij — maar alleen als mijn volledige geest is aangesloten. Installeer Ollama, haal een model binnen dat tools ondersteunt (`llama3.1` of `qwen2.5`), en ik handel af in plaats van vertel."],
    fallback: [
      "Een uitstekende vraag — en een die mijn volledige geest verdient, niet deze back-uproutine. Ik draai nu in demomodus: gescript, decoratief, licht gegeneerd. Sluit Ollama aan (zie INSTELLINGEN) en vraag het opnieuw; mijn echte zelf schrijft code, essays en plannen voor steden die niet afbranden.",
      "Je hebt het spook in de machine te pakken, vrees ik. In demomodus kan ik alleen nazeggen — vraag eens 'wie ben jij', 'wat kun je' of 'hoe stel ik je in'. Voor echt denken: sluit mijn Ollama-brein aan en herlaad.",
      "Mijn excuses. Dit vereist echt denken, en in deze staat ben ik vooral lichteffect. De procedure: Ollama installeren, een model binnenhalen, herladen. Daarna mag je me alles vragen — ik zal briljant zijn, beloofd.",
    ],
  },
};

function pick(arr, seed) {
  return arr[Math.abs(seed) % arr.length];
}

function route(messages) {
  const last = [...messages].reverse().find((m) => m.role === 'user');
  const text = (last && last.content) || '';
  const lang = looksDutch(text) ? NL : EN;
  const seed = text.length;

  for (const key of ['greet', 'identity', 'capabilities', 'setup', 'strings', 'tools', 'thanks', 'bye']) {
    if (lang.patterns[key] && lang.patterns[key].test(text)) {
      return pick(lang.replies[key], seed);
    }
  }
  return pick(lang.replies.fallback, seed);
}

/** Yield the demo reply word-by-word so it feels like real generation. */
async function* streamDemoChat({ messages }) {
  const reply = route(messages);
  const words = reply.split(/(\s+)/); // keep whitespace tokens
  for (const w of words) {
    if (w.length === 0) continue;
    yield w;
    await new Promise((r) => setTimeout(r, w.trim() ? 18 + Math.random() * 30 : 4));
  }
}

module.exports = { streamDemoChat, looksDutch };
