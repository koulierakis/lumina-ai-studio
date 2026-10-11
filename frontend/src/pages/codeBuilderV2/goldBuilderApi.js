import { api } from '../../lib/api';

const GB = '/gb';
const unwrap = (promise) => promise.then((r) => r.data).catch((err) => {
  const detail = err?.response?.data?.detail;
  const message = typeof detail === 'string' ? detail : detail?.message || err?.response?.data?.message || err.message;
  throw new Error(`${err?.response?.status ? `HTTP ${err.response.status}: ` : ''}${message}`);
});

export const ACTIVE = ['understanding', 'inspecting', 'planning', 'generating', 'media', 'installing', 'building',
  'typechecking', 'linting', 'testing', 'starting', 'verifying', 'diagnosing', 'repairing', 'recovering',
  'self_reviewing', 'independent_review', 'review_repair', 'final_verifying'];

export const gb = {
  providers: () => unwrap(api.get(`${GB}/providers`)),
  stacks: () => unwrap(api.get(`${GB}/stacks`)),
  draft: (body) => unwrap(api.post(`${GB}/jobs/draft`, body)),
  draftExisting: (body) => unwrap(api.post(`${GB}/jobs/existing/draft`, body)),
  attach: (id, files) => {
    const form = new FormData();
    Array.from(files).forEach((f) => form.append('files', f));
    return unwrap(api.post(`${GB}/jobs/${id}/attachments`, form, { timeout: 120000 }));
  },
  start: (id) => unwrap(api.post(`${GB}/jobs/${id}/start`)),
  job: (id) => unwrap(api.get(`${GB}/jobs/${id}`)),
  iterate: (id, request) => unwrap(api.post(`${GB}/jobs/${id}/iterate`, { request })),
  verify: (id) => unwrap(api.post(`${GB}/jobs/${id}/verify`, {}, { timeout: 180000 })),
  preview: (id) => unwrap(api.get(`${GB}/jobs/${id}/preview`)),
  startPreview: (id) => unwrap(api.post(`${GB}/jobs/${id}/preview/start`, {}, { timeout: 180000 })),
  session: () => unwrap(api.post('/gb-session')),
  blob: (path) => unwrap(api.get(`${GB}${path}`, { responseType: 'blob', timeout: 120000 })),
};
