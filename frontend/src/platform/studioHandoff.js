const CREATION_WORDS = [
  'φτιάξε', 'φτιαξε', 'φτιάξεις', 'φτιαξεις', 'δημιούργησε', 'δημιουργησε',
  'δημιουργήσεις', 'δημιουργησεις', 'κάνε', 'κανε', 'κάνεις', 'κανεις',
  'ετοίμασε', 'ετοιμασε', 'ετοιμάσεις', 'ετοιμασεις', 'παράγαγε', 'παραγαγε',
  'παράγεις', 'παραγεις', 'generate', 'create', 'make',
];

export const STUDIO_TARGETS = {
  document: { route: '/studio/documents', label: 'Lumina Documents' },
  image: { route: '/studio/generate', label: 'Image Studio' },
  voice: { route: '/studio/voice-studio', label: 'Voice Studio' },
  video: { route: '/studio/video-studio', label: 'Video Studio' },
};

const TARGET_WORDS = {
  document: ['έγγραφο', 'εγγραφο', 'συμφωνητικό', 'συμφωνητικο', 'σύμβαση', 'συμβαση', 'επιστολή', 'επιστολη', 'invoice', 'τιμολόγιο', 'βιογραφικό', 'βιογραφικο', 'document', 'pdf', 'word'],
  image: ['φωτογραφία', 'φωτογραφια', 'φωτό', 'φωτο', 'εικόνα', 'εικονα', 'image', 'photo', 'poster', 'αφίσα', 'αφισα'],
  voice: ['φωνή', 'φωνη', 'ηχητικό', 'ηχητικο', 'αφήγηση', 'αφηγηση', 'voice', 'audio', 'εκφώνηση', 'εκφωνηση'],
  video: ['βίντεο', 'βιντεο', 'video', 'reel', 'ταινία', 'ταινια', 'animation'],
};
const TARGET_PRIORITY = ['video', 'voice', 'document', 'image'];

function normalized(value) {
  return String(value || '').trim().toLocaleLowerCase('el-GR');
}

function optionsFromText(text, target) {
  const aspect = text.match(/\b(1:1|16:9|9:16|4:5|3:2)\b/)?.[1];
  const duration = Number(text.match(/\b(3|5|8)\s*(?:δευτερ|sec)/)?.[1] || 0);
  return {
    ...(aspect ? { aspect } : {}),
    ...(target === 'video' && duration ? { duration } : {}),
    ...(target === 'voice' && text.includes('ανδρ') ? { voiceId: 'andreas' } : {}),
    ...(target === 'voice' && text.includes('γυναικ') ? { voiceId: 'ariadni' } : {}),
    language: /[α-ωάέήίόύώϊϋΐΰ]/i.test(text) ? 'el' : 'en',
  };
}

export function detectStudioIntent(message) {
  const text = normalized(message);
  if (!text || !CREATION_WORDS.some((word) => text.includes(word))) return null;

  const target = TARGET_PRIORITY.find((key) => (
    TARGET_WORDS[key].some((word) => text.includes(word))
  ));
  if (!target) return null;

  return {
    id: `mind-${globalThis.crypto?.randomUUID?.() || Date.now()}`,
    target,
    route: STUDIO_TARGETS[target].route,
    label: STUDIO_TARGETS[target].label,
    prompt: String(message || '').trim(),
    options: optionsFromText(text, target),
    autoRun: true,
    source: 'lumina-mind',
  };
}

export function handoffForTarget(locationState, target) {
  const handoff = locationState?.studioHandoff;
  if (!handoff || handoff.source !== 'lumina-mind' || handoff.target !== target) return null;
  if (!handoff.autoRun || !String(handoff.prompt || '').trim()) return null;
  return handoff;
}
