import { API_BASE } from '../lib/api';

export const STATUS_STYLE = {
  ready: 'bg-emerald-400', working: 'bg-gold', warning: 'bg-amber-400', offline: 'bg-white/30', error: 'bg-red-400',
  queued: 'bg-white/35', running: 'bg-gold', completed: 'bg-emerald-400', failed: 'bg-red-400', cancelled: 'bg-white/35',
};

const EMPTY_REPOSITORY = {
  branch: 'Unavailable', clean: false, changed_files: [], uncommitted_count: 0,
  recent_commits: [], last_commit: 'Repository information is unavailable.',
};

export const EMPTY_DEVELOPER_OVERVIEW = {
  health: { checks: [], metrics: {}, refreshed_at: null }, repository: EMPTY_REPOSITORY,
  tasks: [], logs: [], media_jobs: [], refreshed_at: null, panel_errors: {},
};

const asObject = (value) => (value && typeof value === 'object' && !Array.isArray(value) ? value : {});
const asArray = (value) => (Array.isArray(value) ? value : []);
const text = (value, fallback = '') => (typeof value === 'string' && value.trim() ? value : fallback);

export function statusLabel(status = '') {
  return ({ ready: 'Ready', working: 'Working', warning: 'Warning', offline: 'Offline', error: 'Error', queued: 'Queued', running: 'Working', completed: 'Completed', failed: 'Failed', cancelled: 'Cancelled' })[status] || 'Unknown';
}

export function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return '—';
  if (seconds < 60) return `${Math.round(seconds)} sec`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

export function relativeTime(value, now = Date.now()) {
  const ms = new Date(value).getTime();
  if (!Number.isFinite(ms)) return 'Recently';
  const minutes = Math.max(0, Math.floor((now - ms) / 60000));
  return minutes < 1 ? 'Just now' : minutes < 60 ? `${minutes}m ago` : `${Math.floor(minutes / 60)}h ago`;
}

export function toSafeErrorMessage(error, fallback = 'This local panel is temporarily unavailable.') {
  if (typeof error === 'string' && error.trim()) return error;
  if (!error) return fallback;
  if (error instanceof Error && error.message) return error.message;
  if (Array.isArray(error)) {
    const message = error.map((item) => toSafeErrorMessage(item, '')).filter(Boolean).join(' ');
    return message || fallback;
  }
  const value = asObject(error);
  if (text(value.message)) return value.message;
  if (text(value.msg)) return value.msg;
  if (text(value.detail)) return value.detail;
  if (value.response?.data) return toSafeErrorMessage(value.response.data, fallback);
  if (value.responseData) return toSafeErrorMessage(value.responseData, fallback);
  if (value.data) return toSafeErrorMessage(value.data, fallback);
  if (value.detail) return toSafeErrorMessage(value.detail, fallback);
  if (value.error) return toSafeErrorMessage(value.error, fallback);
  return fallback;
}

const normalizeCheck = (value) => {
  const item = asObject(value);
  return { name: text(item.name, 'Local service'), status: text(item.status, 'warning'), detail: text(item.detail, 'No additional details are available.') };
};
const normalizeTask = (value) => {
  const item = asObject(value);
  return { ...item, id: text(item.id, `local-${Math.random().toString(36).slice(2)}`), label: text(item.label, 'Local task'), status: text(item.status, 'warning') };
};
const normalizeLog = (value) => {
  const item = asObject(value);
  return { ...item, timestamp: text(item.timestamp), severity: text(item.severity, 'info'), source: text(item.source, 'local'), message: text(item.message, 'No message was recorded.') };
};
const normalizeMediaJob = (value) => {
  const item = asObject(value);
  return { ...item, id: text(item.id, `job-${Math.random().toString(36).slice(2)}`), title: text(item.title, 'Application job'), status: text(item.status, 'unknown') };
};

export function normalizeDeveloperOverview(payload) {
  const source = asObject(payload);
  const health = asObject(source.health);
  const repository = asObject(source.repository);
  return {
    health: { checks: asArray(health.checks).map(normalizeCheck), metrics: asObject(health.metrics), refreshed_at: text(health.refreshed_at) || null },
    repository: {
      ...EMPTY_REPOSITORY, ...repository,
      branch: text(repository.branch, EMPTY_REPOSITORY.branch), clean: repository.clean === true,
      changed_files: asArray(repository.changed_files).map((item) => ({ status: text(asObject(item).status, 'modified'), path: text(asObject(item).path, 'Unknown file') })),
      recent_commits: asArray(repository.recent_commits).filter((item) => typeof item === 'string'),
      uncommitted_count: Number.isFinite(repository.uncommitted_count) ? repository.uncommitted_count : 0,
      last_commit: text(repository.last_commit, EMPTY_REPOSITORY.last_commit),
    },
    tasks: asArray(source.tasks).map(normalizeTask), logs: asArray(source.logs).map(normalizeLog),
    media_jobs: asArray(source.media_jobs).map(normalizeMediaJob), refreshed_at: text(source.refreshed_at) || null,
    panel_errors: asObject(source.panel_errors),
  };
}

export function mergeDeveloperEvent(current, event, payload) {
  const overview = normalizeDeveloperOverview(current);
  if (event === 'snapshot') return normalizeDeveloperOverview({ ...overview, ...asObject(payload), tasks: asObject(payload).tasks, logs: asObject(payload).logs });
  if (event === 'task') {
    const task = normalizeTask(payload);
    return { ...overview, tasks: [task, ...overview.tasks.filter((item) => item.id !== task.id)] };
  }
  if (event === 'log') return { ...overview, logs: [normalizeLog(payload), ...overview.logs].slice(0, 300) };
  return overview;
}

export function pollingFallbackForSse(error) {
  return { enabled: true, message: toSafeErrorMessage(error, 'Live updates are unavailable. Refreshing periodically instead.') };
}

export async function subscribeDeveloperEvents(onEvent, signal) {
  const token = localStorage.getItem('lumina_token');
  const response = await fetch(`${API_BASE}/developer/events`, { headers: token ? { Authorization: `Bearer ${token}` } : {}, signal });
  if (!response.ok || !response.body) {
    let body = null;
    try { body = await response.json(); } catch { /* A local service may not return JSON. */ }
    throw new Error(toSafeErrorMessage(body, `Live developer updates are unavailable (${response.status || 'offline'}).`));
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (!signal.aborted) {
    const { done, value } = await reader.read();
    if (done) throw new Error('Live developer updates ended. Refreshing periodically instead.');
    buffer += decoder.decode(value, { stream: true });
    const packets = buffer.split('\n\n'); buffer = packets.pop() || '';
    packets.forEach((packet) => {
      const event = packet.match(/^event: (.+)$/m)?.[1];
      const raw = packet.match(/^data: (.+)$/m)?.[1];
      if (event && raw) { try { onEvent(event, JSON.parse(raw)); } catch { /* Ignore malformed local events. */ } }
    });
  }
}
