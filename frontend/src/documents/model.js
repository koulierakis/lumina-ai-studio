import { apiDelete, apiGet, apiPatch, apiPost, apiPut, uploadFormData, API_BASE } from '../lib/api';
import { runtimeStudioJobPayload } from '../runtime/model';

export const DOCUMENT_TYPES = [
  'Contracts', 'Commercial Agreements', 'Sales Agreements', 'Purchase Agreements', 'Service Agreements', 'Master Agreements', 'Framework Agreements', 'Non Disclosure Agreements', 'NCNDA', 'IMFPA', 'Memorandum of Understanding', 'Letters of Intent', 'Invoices', 'Proforma Invoices', 'Corporate Letters', 'Business Letters', 'Bank Correspondence', 'Compliance Documents', 'Corporate Resolutions', 'Certificates', 'Declarations', 'Power of Attorney', 'Minutes', 'Policies', 'Reports', 'Manuals', 'Executive Summaries', 'Business Proposals', 'Investment Proposals', 'Pitch Deck Documents', 'Tender Documents', 'Employment Documents', 'Legal Documents', 'Custom Documents',
];

export const DOCUMENT_CREATION_MODES = ['prompt', 'template', 'uploaded', 'rewrite', 'merge', 'continue', 'translate', 'improve', 'summarize', 'expand', 'style'];
export const EXPORT_FORMATS = ['pdf', 'docx', 'html', 'markdown', 'rtf', 'txt'];

export const DEFAULT_COMPANY_PROFILE = {
  company_name: 'Lumina Corporate Holdings',
  primary_color: '#B9985A',
  secondary_color: '#111827',
  accent_color: '#E8D8A8',
  font_heading: 'Georgia',
  font_body: 'Inter',
  signatures: [],
  addresses: [],
  contact_information: {},
  legal_information: {},
};

export const documentApi = {
  templates: () => apiGet('/documents/templates'),
  templateLibrary: (params = {}) => apiGet('/documents/template-library', { params }),
  createTemplate: (payload) => apiPost('/documents/template-library', payload),
  updateTemplate: (id, payload) => apiPatch(`/documents/template-library/${id}`, payload),
  templateAction: (id, action) => apiPost(`/documents/template-library/${id}/${action}`, {}),
  deleteTemplate: (id) => apiDelete(`/documents/template-library/${id}`),
  mergeTemplate: (id, payload) => apiPost(`/documents/template-library/${id}/merge`, payload),
  templateVersions: (id) => apiGet(`/documents/template-library/${id}/versions`),
  validateTemplate: (id, payload = {}) => apiPost(`/documents/template-library/${id}/validate`, payload),
  restoreTemplateVersion: (id, versionId) => apiPost(`/documents/template-library/${id}/versions/${versionId}/restore`, {}),
  companies: () => apiGet('/documents/companies'),
  searchCompanies: (q) => apiGet('/documents/companies/search', { params: { q } }),
  companyDashboard: (id) => apiGet(`/documents/companies/${id}/dashboard`),
  updateCompany: (id, payload) => apiPatch(`/documents/companies/${id}`, payload),
  companyLifecycle: (id, action) => apiPost(`/documents/companies/${id}/${action}`, {}),
  companyVersions: (id) => apiGet(`/documents/companies/${id}/versions`),
  restoreCompanyVersion: (id, versionId) => apiPost(`/documents/companies/${id}/versions/${versionId}/restore`, {}),
  createCompany: (payload) => apiPost('/documents/companies', payload),
  profile: () => apiGet('/documents/company-profile'),
  saveProfile: (payload) => apiPut('/documents/company-profile', payload),
  people: (params = {}) => apiGet('/documents/people', { params }),
  savePerson: (payload) => apiPost('/documents/people', payload),
  banks: (params = {}) => apiGet('/documents/banks', { params }),
  saveBank: (payload) => apiPost('/documents/banks', payload),
  clauses: (params = {}) => apiGet('/documents/clauses', { params }),
  saveClause: (payload) => apiPost('/documents/clauses', payload),
  folders: () => apiGet('/documents/folders'),
  createFolder: (payload) => apiPost('/documents/folders', payload),
  renameFolder: (id, name) => apiPut(`/documents/folders/${id}`, { name }),
  moveFolder: (id, parent_id = null) => apiPost(`/documents/folders/${id}/move`, { parent_id }),
  deleteFolder: (id) => apiDelete(`/documents/folders/${id}`),
  collections: (params = {}) => apiGet('/documents/collections', { params }),
  createCollection: (payload) => apiPost('/documents/collections', payload),
  updateCollection: (id, payload) => apiPatch(`/documents/collections/${id}`, payload),
  deleteCollection: (id) => apiDelete(`/documents/collections/${id}`),
  list: (params = {}) => apiGet('/documents', { params }),
  create: (payload) => apiPost('/documents', payload),
  createPackage: (payload) => apiPost('/documents/packages', payload),
  classify: (payload) => apiPost('/documents/classify', payload),
  generate: (payload) => apiPost('/documents/generate', payload),
  update: (id, payload) => apiPatch(`/documents/${id}`, payload),
  lifecycle: (id, action) => apiPost(`/documents/${id}/${action}`, {}),
  batch: (payload) => apiPost('/documents/batch', payload),
  exportJob: (payload) => apiPost('/documents/export-jobs', payload),
  libraryIndex: (params = {}) => apiGet('/documents/library/index', { params }),
  design: (id, payload) => apiPatch(`/documents/${id}/design`, payload),
  redesign: (id) => apiPost(`/documents/${id}/redesign`, {}),
  quality: (id) => apiGet(`/documents/${id}/quality`),
  compare: (id, rightId) => apiGet(`/documents/${id}/compare/${rightId}`),
  versionDiff: (id, versionId) => apiGet(`/documents/${id}/diff/${versionId}`),
  previewUrl: (id) => `${API_BASE}/documents/${id}/preview`,
  remove: (id) => apiDelete(`/documents/${id}`),
  versions: (id) => apiGet(`/documents/${id}/versions`),
  activity: (id, params = {}) => apiGet(`/documents/${id}/activity`, { params }),
  review: (id) => apiGet(`/documents/${id}/review`),
  createReviewItem: (id, payload) => apiPost(`/documents/${id}/review`, payload),
  reviewAction: (id, commentId, payload) => apiPost(`/documents/${id}/review/${commentId}`, payload),
  trackChanges: (id, params = {}) => apiGet(`/documents/${id}/track-changes`, { params }),
  createTrackChange: (id, payload) => apiPost(`/documents/${id}/track-changes`, payload),
  trackChangeAction: (id, payload) => apiPost(`/documents/${id}/track-changes/actions`, payload),
  lock: (id, payload) => apiPost(`/documents/${id}/lock`, payload),
  analyze: (id, payload) => apiPost(`/documents/${id}/analysis`, payload),
  legalReview: (id) => apiPost(`/documents/${id}/legal-review`, {}),
  insertClause: (id, clauseId) => apiPost(`/documents/${id}/clauses/${clauseId}`, {}),
  operate: (id, payload) => apiPost(`/documents/${id}/operate`, payload),
  versionAction: (id, versionId, payload) => apiPost(`/documents/${id}/versions/${versionId}`, payload),
  runtimeAnalyzePayload: (id, payload) => runtimeStudioJobPayload('documents', 'llm', { document_id: id, ...payload }),
  importFile: (file, metadata = {}) => {
    const form = new FormData();
    form.append('file', file);
    Object.entries(metadata).forEach(([key, value]) => form.append(key, value || ''));
    return uploadFormData('/documents/import', form, { timeout: 60000 });
  },
};

export function exportDocumentUrl(documentId, format) {
  return `${API_BASE}/documents/${documentId}/export/${format}`;
}

export function makeDocumentDownloadHeaders() {
  const token = localStorage.getItem('lumina_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function summarizeDocument(document) {
  const text = document?.content_text || document?.searchable_text || '';
  return text.length > 220 ? `${text.slice(0, 220)}…` : text;
}

export function documentStats(document) {
  const text = document?.content_text || document?.searchable_text || '';
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  return { words, versions: document?.version_number || 1, exports: document?.export_media_ids?.length || 0 };
}

export function summarizeReviewState(document) {
  const review = document?.metadata?.review || {};
  const track = document?.metadata?.track_changes || {};
  const lock = document?.metadata?.lock || {};
  return {
    reviewStatus: review.status || document?.status || 'draft',
    openComments: review.open_count || 0,
    resolvedComments: review.resolved_count || 0,
    pendingChanges: track.pending_count || 0,
    acceptedChanges: track.accepted_count || 0,
    rejectedChanges: track.rejected_count || 0,
    locked: Boolean(lock.locked),
    lockedBy: lock.owner || '',
  };
}

export function buildVirtualizedDocumentWindow(documents = [], scrollTop = 0, rowHeight = 72, viewportHeight = 720) {
  const safeRowHeight = Math.max(24, rowHeight);
  const start = Math.max(0, Math.floor(scrollTop / safeRowHeight) - 5);
  const visibleCount = Math.ceil(viewportHeight / safeRowHeight) + 10;
  const end = Math.min(documents.length, start + visibleCount);
  return {
    start,
    end,
    totalHeight: documents.length * safeRowHeight,
    items: documents.slice(start, end).map((document, offset) => ({
      document,
      index: start + offset,
      top: (start + offset) * safeRowHeight,
    })),
  };
}

export function normalizeDiffRows(diff = {}) {
  return (diff.side_by_side || []).map((row) => ({
    ...row,
    marker: row.status === 'inserted' ? '+' : row.status === 'deleted' ? '-' : row.status === 'modified' ? '~' : ' ',
  }));
}
