'use strict';
/* =========================================================
   VoiceOS i18n — English / Nederlands
   Covers: UI chrome, chips, spoken responses, card labels,
   voice-command phrases, and Dutch time/filler vocabulary.
   JSON response keys stay English (that's the API schema).
   ========================================================= */

const I18N = {
  en: {
    // chrome
    hintTitle: 'VoiceOS is listening.',
    hintSub: 'Type a command below, tap the mic, or click a suggestion. Try agent mode: “Send email to John about the meeting.”',
    composerHint: '⌃ Space to talk · Enter to run',
    inputPlaceholder: 'Say it once… e.g. "Schedule meeting with Sarah next week"',
    panelSession: 'Session',
    panelJson: 'Response JSON',
    panelJsonNote: '— every turn',
    // labels used in cards
    lbl: { to: 'To', subject: 'Subject', when: 'When', with: 'With', what: 'What', task: 'Task', send: 'SEND', book: 'BOOK', add: 'ADD', confirm: 'CONFIRM', cancel: 'CANCEL' },
    // settings
    setRecordSpeed: 'Speed', setConfirmations: 'Confirmations', setVerbosity: 'Verbosity',
    setPrivacy: 'Privacy', setHotkey: 'Hotkey', setLanguage: 'Language', setVoice: 'Voice',
    resetOnboarding: 'Reset onboarding', wipeData: 'Clear local data',
    optSlow: 'Slow', optNormal: 'Normal', optFast: 'Fast',
    optAlways: 'Always', optSometimes: 'Big stuff only', optNever: 'Never',
    // onboarding
    obSub: 'Say it once, let it go. A voice layer for everything you do.',
    obSpeed: 'Speaking speed', obConfirm: 'Ask before acting…', obVoice: 'Voice', obLang: 'Language',
    obPrivacy: '🔒 Audio and transcripts never leave this device.',
    obStart: 'Start using VoiceOS',
    obFoot: 'Try it: “Send email to John about the meeting.”',
    welcomeTitle: 'VoiceOS is ready',
    welcomeSub: 'Try: “Send email to John about the meeting.”',
    // suggestion chips
    chips: [
      'Send John the latest project deck',
      'Morning briefing',
      'Send email to John about the meeting',
      'Schedule meeting with Sarah next week',
      'Find last year’s tax returns',
      'Reply to Maya',
      'Create task: review the launch plan',
      'Search notes for checklist',
      'Remind me to call Joan tomorrow at 9am',
      'Take a note: the new onboarding flow tested well',
      'What’s my next meeting?',
      'Send message',
      'Search web for focus music',
      'Open Notes',
    ],
  },

  nl: {
    hintTitle: 'VoiceOS luistert.',
    hintSub: 'Typ hieronder een opdracht, tik op de mic, of kies een suggestie. Probeer de agentmodus: “Stuur een e-mail naar John over de vergadering.”',
    composerHint: '⌃ Spatie om te praten · Enter om uit te voeren',
    inputPlaceholder: 'Zeg het één keer… bijv. "Plan een vergadering met Sarah volgende week"',
    panelSession: 'Sessie',
    panelJson: 'Response-JSON',
    panelJsonNote: '— elke beurt',
    lbl: { to: 'Aan', subject: 'Onderwerp', when: 'Wanneer', with: 'Met', what: 'Wat', task: 'Taak', send: 'VERSTUUR', book: 'PLAN', add: 'TOEVOEGEN', confirm: 'BEVESTIG', cancel: 'ANNULEREN' },
    setRecordSpeed: 'Snelheid', setConfirmations: 'Bevestigingen', setVerbosity: 'Uitgebreidheid',
    setPrivacy: 'Privacy', setHotkey: 'Sneltoets', setLanguage: 'Taal', setVoice: 'Stem',
    resetOnboarding: 'Introductie opnieuw', wipeData: 'Lokale data wissen',
    optSlow: 'Langzaam', optNormal: 'Normaal', optFast: 'Snel',
    optAlways: 'Altijd', optSometimes: 'Alleen belangrijke', optNever: 'Nooit',
    obSub: 'Zeg het één keer, en het is geregeld. Een stemlaag voor alles wat je doet.',
    obSpeed: 'Spreeksnelheid', obConfirm: 'Vraag om bevestiging…', obVoice: 'Stem', obLang: 'Taal',
    obPrivacy: '🔒 Audio en transcripties verlaten dit apparaat nooit.',
    obStart: 'Begin met VoiceOS',
    obFoot: 'Probeer: “Stuur een e-mail naar John over de vergadering.”',
    welcomeTitle: 'VoiceOS is klaar',
    welcomeSub: 'Probeer: “Stuur een e-mail naar John over de vergadering.”',
    chips: [
      'Stuur John de nieuwste projectpresentatie',
      'Ochtendbriefing',
      'Stuur een e-mail naar John over de vergadering',
      'Plan een vergadering met Sarah volgende week',
      'Zoek de belastingaangifte van vorig jaar',
      'Beantwoord Maya',
      'Maak taak: het lanceringsplan nalopen',
      'Zoek in notities naar checklist',
      'Herinner me eraan Joan morgen om 9 uur te bellen',
      'Maak een notitie: de nieuwe onboarding-flow testte goed',
      'Wat is mijn volgende vergadering?',
      'Stuur een bericht',
      'Zoek op internet naar focustiming',
      'Open Notities',
    ],
  },
};

/* ---- app names synonyms (Dutch macOS-style app names → internal) ---- */
const APP_NAMES_NL = {
  notities: 'Notes', notitie: 'Notes',
  bestanden: 'Files', bestand: 'Files', verkenner: 'Files', finder: 'Files',
  berichten: 'Messages', agenda: 'Calendar', kalender: 'Calendar',
  taken: 'Tasks', mail: 'Mail', email: 'Mail', 'e-mail': 'Mail',
};

/* ---- Dutch time vocabulary for resolveDate ---- */
const NL_DAYS = { zondag: 0, maandag: 1, dinsdag: 2, woensdag: 3, donderdag: 4, vrijdag: 5, zaterdag: 6 };

/* ---- Dutch filler words for dictation cleanup ---- */
const NL_FILLERS = ['eh', 'ehm', 'uh', 'zeg maar', 'weet je', 'eigenlijk gezegd', 'dus eh'];

/* ---- Dutch meeting-kind normalization ---- */
const KIND_EN = { vergadering: 'meeting', gesprek: 'call', afspraak: 'meeting' };

/* ---- helpers ---- */
function detectLang() {
  try {
    const nav = (typeof navigator !== 'undefined' && navigator.language) || 'en';
    return nav.toLowerCase().startsWith('nl') ? 'nl' : 'en';
  } catch (_) { return 'en'; }
}
