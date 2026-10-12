export const CONTROL_CENTER_TOOLS = [
  { key: 'code-builder', label: 'Google Code Builder', description: 'Δημιουργία & εξέλιξη εφαρμογών με AI agent & ζωντανή προεπισκόπηση.', to: '/studio/code-builder', icon: 'code' },
  { key: 'mind', label: 'LUMINA Mind', description: 'Στρατηγικός σύμβουλος, Life Coach & Orchestrator.', to: '/studio/mind', icon: 'mind' },
  { key: 'image', label: 'Image Studio', description: 'Δημιουργία εικόνων υψηλής πιστότητας.', to: '/studio/generate', icon: 'image' },
  { key: 'video', label: 'Video Studio', description: 'Παραγωγή & επεξεργασία AI βίντεο και motion.', to: '/studio/video-studio', icon: 'video' },
  { key: 'voice', label: 'Voice Studio', description: 'Ηχογράφηση φωνής, απομαγνητοφώνηση & Voice AI.', to: '/studio/voice-studio', icon: 'voice' },
  { key: 'documents', label: 'Document Studio', description: 'Σύνταξη & διαμόρφωση εγγράφων με AI.', to: '/studio/documents', icon: 'document' },
  { key: 'settings', label: 'Workspace Settings', description: 'Διαχείριση περιβάλλοντος και ρυθμίσεων Lumina.', to: '/studio/settings', icon: 'settings' },
];

export function activeJobs(jobs = []) {
  return jobs.filter((job) => ['queued', 'preparing', 'uploading', 'processing', 'rendering'].includes(job.status));
}

export function formatRelativeTime(value, now = Date.now()) {
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return 'Recently';
  const minutes = Math.max(0, Math.floor((now - timestamp) / 60000));
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function buildMessages({ jobs = [], providers = [], gallery = [], system = null }) {
  const messages = [];
  const running = activeJobs(jobs);
  const readyProviders = providers.filter((provider) => provider.configured && provider.healthy);
  if (system?.system_ready) messages.push({ title: 'System ready — backend, frontend and local AI are online', tone: 'green' });
  else if (system?.overall_readiness === 'degraded') messages.push({ title: 'System is degraded — check Local AI or coding model', tone: 'gold' });
  if (running.length) messages.push({ title: `${running.length} job${running.length === 1 ? '' : 's'} in progress`, tone: 'gold' });
  if (readyProviders.length) messages.push({ title: `${readyProviders.length} AI provider${readyProviders.length === 1 ? '' : 's'} ready`, tone: 'green' });
  if (!gallery.length) messages.push({ title: 'Your gallery is ready for its first creation', tone: 'muted' });
  return messages.slice(0, 3);
}

export function suggestedActions({ jobs = [], gallery = [], projects = [] }) {
  const actions = [];
  if (!gallery.length) actions.push({ title: 'Create your first image', description: 'Start with a guided AI generation.', to: '/studio/generate' });
  if (activeJobs(jobs).length) actions.push({ title: 'Review active jobs', description: 'See what Lumina is currently creating.', to: '/studio/dashboard#jobs' });
  if (gallery.length) actions.push({ title: 'Refine a recent image', description: 'Open a gallery asset in the AI editor.', to: '/studio/editor' });
  if (!projects.length) actions.push({ title: 'Plan a video project', description: 'Create a simple timeline when you are ready.', to: '/studio/video-studio' });
  return actions.slice(0, 3);
}
