import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, ChevronUp, FileText, Save, Sparkles, XCircle } from 'lucide-react';
import {
  DOCUMENT_AI_PROVIDERS,
  documentApi,
  friendlyDocumentAIError,
} from '../../documents/model';
import { apiGet } from '../../lib/api';

const DEFAULT_DOCUMENT_TYPES = [
  'nda', 'consulting_agreement', 'company_profile', 'board_resolution',
  'corporate_resolution', 'banking_cover_letter', 'aml_declaration',
  'professional_cv',
];

const CV_STYLES = [
  ['minimal', 'Minimal'],
  ['professional', 'Professional'],
  ['modern', 'Modern'],
  ['executive', 'Executive'],
  ['corporate', 'Corporate'],
  ['elegant', 'Elegant'],
  ['creative', 'Creative'],
  ['luxury', 'Luxury'],
  ['ats', 'ATS-friendly'],
];

function ProviderSelect({ value, onChange, label = 'Provider' }) {
  return (
    <label className="doc-ai-field doc-ai-provider-field">
      <span>{label}</span>
      <select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">Automatic (Ollama)</option>
        {DOCUMENT_AI_PROVIDERS.map((providerName) => (
          <option key={providerName} value={providerName}>{providerName === 'groq' ? 'Groq' : 'Ollama'}</option>
        ))}
      </select>
    </label>
  );
}

function ProviderReadiness({ payload, loading, onRefresh }) {
  const providers = payload?.providers || {};
  return (
    <section className="doc-ai-provider-readiness" aria-label="AI provider readiness">
      <div className="doc-ai-preview-heading">
        <strong>AI readiness</strong>
        <button type="button" onClick={onRefresh} disabled={loading}>{loading ? 'Checking…' : 'Refresh'}</button>
      </div>
      {DOCUMENT_AI_PROVIDERS.map((name) => {
        const status = providers[name] || {};
        const ready = Boolean(status.ready ?? status.available);
        const model = status.selected_structured_document_model || status.selected_document_model;
        return (
          <div key={name} className={`doc-ai-pack-summary ${ready ? 'complete' : 'failed'}`}>
            {ready ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
            <span><strong>{name === 'groq' ? 'Groq' : 'Ollama'}</strong>{model ? ` · ${model}` : ''} · {ready ? 'ready' : (status.error || 'unavailable')}</span>
          </div>
        );
      })}
    </section>
  );
}

function PreviewCard({ preview, title, onApply, onSave, saving }) {
  if (!preview) return null;
  const document = preview.document || {};
  const metadata = preview.generation?.metadata || {};
  const unresolved = document.unresolved_fields || preview.intentional_blank_fields || [];
  return (
    <section className="doc-ai-preview" aria-label={`${title} preview`}>
      <div className="doc-ai-preview-heading">
        <strong>{document.title || title}</strong>
        <span className="doc-ai-status generated">Preview only</span>
      </div>
      <p>{document.content || document.content_text || 'Structured preview is ready for review.'}</p>
      <div className="doc-ai-metadata">
        {metadata.provider_used && <span>Provider: {metadata.provider_used}</span>}
        {metadata.validation_status && <span>Validation: {metadata.validation_status}</span>}
        {metadata.fallback_used && <span className="doc-ai-warning">Fallback used</span>}
      </div>
      {unresolved.length > 0 && (
        <div className="doc-ai-warning" role="status">
          Placeholders retained: {unresolved.join(', ')}
        </div>
      )}
      <div className="doc-ai-selection-actions">
        <button type="button" className="doc-ai-apply" onClick={() => onApply(preview)}>
          Apply to Current Document
        </button>
        <button type="button" onClick={() => onSave(preview)} disabled={saving}>
          <Save size={14} /> {saving ? 'Saving…' : 'Save as New Document'}
        </button>
      </div>
    </section>
  );
}

function previewToDocumentPayload(preview, profileId, fallbackTitle = 'AI Document') {
  const source = preview?.document || {};
  const contentHtml = source.content_html || '';
  const contentText = source.content_text || source.content || '';
  return {
    title: source.title || fallbackTitle,
    document_type: source.document_type || source.type || 'custom_document',
    category: source.category || 'AI Generated',
    tags: ['ai-generated', 'document-studio'],
    company_profile_id: profileId || undefined,
    content_html: contentHtml || `<article><p>${String(contentText).replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]))}</p></article>`,
    content_text: contentText,
    searchable_text: contentText,
    metadata: {
      ...(source.metadata || {}),
      ai_generation: preview?.generation || {},
      intentional_blank_fields: preview?.intentional_blank_fields || source.unresolved_fields || [],
      persisted_from_preview: true,
    },
  };
}

export default function DocumentAIAssistantPanel({ profileId, onApplyPreview, onDocumentSaved, onClose }) {
  const [objective, setObjective] = useState('');
  const [naturalRequest, setNaturalRequest] = useState('');
  const [advisor, setAdvisor] = useState(null);
  const [selectedTypes, setSelectedTypes] = useState([]);
  const [documentType, setDocumentType] = useState('nda');
  const [provider, setProvider] = useState('');
  const [fallbackProvider, setFallbackProvider] = useState('');
  const [naturalPreview, setNaturalPreview] = useState(null);
  const [aiPreview, setAIPreview] = useState(null);
  const [packPreview, setPackPreview] = useState(null);
  const [cvPreview, setCvPreview] = useState(null);
  const [cvDetails, setCvDetails] = useState('');
  const [cvLanguage, setCvLanguage] = useState('el');
  const [cvStyle, setCvStyle] = useState('professional');
  const [cvLayout, setCvLayout] = useState('single-column');
  const [cvLength, setCvLength] = useState('2-pages');
  const [cvPhoto, setCvPhoto] = useState('without-photo');
  const [loadingAction, setLoadingAction] = useState('');
  const [error, setError] = useState('');
  const [providerStatus, setProviderStatus] = useState(null);
  const [providerStatusLoading, setProviderStatusLoading] = useState(false);

  const recommendations = useMemo(() => advisor?.recommendations || [], [advisor?.recommendations]);
  const documentTypes = useMemo(() => [...new Set([
    ...recommendations.map((item) => item.document_type), ...DEFAULT_DOCUMENT_TYPES,
  ])], [recommendations]);
  const requiredTypes = recommendations.filter((item) => item.priority === 'required').map((item) => item.document_type);

  async function refreshProviderStatus() {
    setProviderStatusLoading(true);
    try {
      setProviderStatus(await apiGet('/documents/ai/providers/status'));
    } catch (caught) {
      setProviderStatus({ providers: {}, any_ready: false });
    } finally {
      setProviderStatusLoading(false);
    }
  }

  useEffect(() => { refreshProviderStatus(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function toggleType(type) {
    setSelectedTypes((current) => current.includes(type) ? current.filter((item) => item !== type) : [...current, type]);
  }

  async function run(action, operation) {
    setLoadingAction(action);
    setError('');
    try { return await operation(); }
    catch (caught) { setError(friendlyDocumentAIError(caught)); await refreshProviderStatus(); return null; }
    finally { setLoadingAction(''); }
  }

  async function analyze() {
    const result = await run('advisor', () => documentApi.packAdvisor({ objective, company_profile_id: profileId }));
    if (!result) return;
    setAdvisor(result);
    setSelectedTypes([]);
    if (result.recommendations?.[0]?.document_type) setDocumentType(result.recommendations[0].document_type);
  }

  async function createNaturalPreview() {
    const result = await run('natural', () => documentApi.naturalCreatePreview({ request: naturalRequest, company_profile_id: profileId, provider }));
    if (result) setNaturalPreview(result);
  }

  async function createCvPreview() {
    const languageLabel = cvLanguage === 'el' ? 'Greek' : 'English';
    const request = [
      `Create a complete professional CV/resume in ${languageLabel}.`,
      `Visual style: ${cvStyle}. Layout: ${cvLayout}. Length: ${cvLength}. Photo preference: ${cvPhoto}.`,
      'Use clear professional section headings, strong hierarchy, concise achievements, consistent dates and polished language.',
      'Do not invent employers, dates, qualifications, skills or contact details. Keep missing facts as explicit placeholders.',
      cvStyle === 'ats' ? 'Prioritize ATS compatibility: simple structure, standard headings, no decorative tables or text boxes.' : '',
      `Candidate information:\n${cvDetails.trim()}`,
    ].filter(Boolean).join('\n');
    const result = await run('cv', () => documentApi.naturalCreatePreview({
      request,
      company_profile_id: profileId,
      provider,
      requested_type: 'professional_cv',
      language: cvLanguage,
      tone: cvStyle === 'creative' ? 'confident' : 'professional',
      style: cvStyle,
      structured_fields: {
        cv_style: cvStyle,
        cv_layout: cvLayout,
        cv_length: cvLength,
        photo_preference: cvPhoto,
        fact_integrity_required: true,
      },
    }));
    if (result) setCvPreview(result);
  }

  async function createAIPreview() {
    const result = await run('generation', () => documentApi.generateAIPreview({
      objective, document_type: documentType, company_profile_id: profileId,
      provider, fallback_provider: fallbackProvider, allow_fallback: Boolean(fallbackProvider),
    }));
    if (result) setAIPreview(result);
  }

  async function createPackPreview() {
    const result = await run('pack', () => documentApi.generatePackPreview({
      objective, company_profile_id: profileId, selected_document_types: selectedTypes,
      provider, fallback_provider: fallbackProvider, allow_fallback: Boolean(fallbackProvider),
    }));
    if (result) setPackPreview(result);
  }

  async function savePreview(preview, fallbackTitle) {
    const created = await run('save', () => documentApi.create(previewToDocumentPayload(preview, profileId, fallbackTitle)));
    if (created) onDocumentSaved?.(created);
    return created;
  }

  async function savePack() {
    const ready = (packPreview?.items || []).filter((item) => item.preview && item.status !== 'failed');
    if (!ready.length) return;
    const saved = await run('save-pack', async () => {
      const documents = [];
      for (const item of ready) {
        // Deliberately sequential: preserve deterministic pack order in the library.
        // eslint-disable-next-line no-await-in-loop
        const created = await documentApi.create(previewToDocumentPayload(item.preview, profileId, item.document_type.replaceAll('_', ' ')));
        documents.push(created);
      }
      return documents;
    });
    if (saved?.length) onDocumentSaved?.(saved[saved.length - 1], saved);
  }

  return (
    <aside className="doc-ai-panel" aria-label="AI document assistance">
      <div className="doc-ai-panel-header">
        <div><Sparkles size={18} /><strong>AI Assistance</strong><span>Preview before applying</span></div>
        <button type="button" onClick={onClose} aria-label="Close AI assistance"><ChevronUp size={18} /></button>
      </div>
      <ProviderReadiness payload={providerStatus} loading={providerStatusLoading} onRefresh={refreshProviderStatus} />
      {error && <div className="doc-ai-error" role="alert"><XCircle size={16} />{error}</div>}
      <div className="doc-ai-grid">
        <section className="doc-ai-section" aria-label="Professional CV builder">
          <h3>Professional CV / Résumé</h3>
          <label className="doc-ai-field"><span>Candidate information</span><textarea aria-label="CV candidate information" value={cvDetails} onChange={(event) => setCvDetails(event.target.value)} placeholder="Paste name, contact details, profile, work history, education, skills, languages and achievements." /></label>
          <div className="doc-ai-selection-actions">
            <label className="doc-ai-field"><span>Language</span><select aria-label="CV language" value={cvLanguage} onChange={(event) => setCvLanguage(event.target.value)}><option value="el">Ελληνικά</option><option value="en">English</option></select></label>
            <label className="doc-ai-field"><span>Style</span><select aria-label="CV style" value={cvStyle} onChange={(event) => setCvStyle(event.target.value)}>{CV_STYLES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label className="doc-ai-field"><span>Layout</span><select aria-label="CV layout" value={cvLayout} onChange={(event) => setCvLayout(event.target.value)}><option value="single-column">Single column</option><option value="two-column">Two columns</option></select></label>
            <label className="doc-ai-field"><span>Length</span><select aria-label="CV length" value={cvLength} onChange={(event) => setCvLength(event.target.value)}><option value="1-page">1 page</option><option value="2-pages">2 pages</option><option value="detailed">Detailed 2+ pages</option></select></label>
            <label className="doc-ai-field"><span>Photo</span><select aria-label="CV photo" value={cvPhoto} onChange={(event) => setCvPhoto(event.target.value)}><option value="without-photo">Without photo</option><option value="with-photo-placeholder">With photo placeholder</option></select></label>
          </div>
          <ProviderSelect value={provider} onChange={setProvider} />
          <button type="button" onClick={createCvPreview} disabled={!cvDetails.trim() || loadingAction}>{loadingAction === 'cv' ? 'Creating CV preview…' : 'Create CV Preview'}</button>
          <PreviewCard preview={cvPreview} title="Professional CV" onApply={onApplyPreview} onSave={(preview) => savePreview(preview, cvLanguage === 'el' ? 'Επαγγελματικό Βιογραφικό' : 'Professional CV')} saving={loadingAction === 'save'} />
        </section>

        <section className="doc-ai-section">
          <h3>Natural creation</h3>
          <label className="doc-ai-field"><span>Describe the document</span><textarea aria-label="Natural document request" value={naturalRequest} onChange={(event) => setNaturalRequest(event.target.value)} placeholder="Create a corporate banking business nature statement." /></label>
          <ProviderSelect value={provider} onChange={setProvider} />
          <button type="button" onClick={createNaturalPreview} disabled={!naturalRequest.trim() || loadingAction}>{loadingAction === 'natural' ? 'Creating preview…' : 'Preview Natural Draft'}</button>
          <PreviewCard preview={naturalPreview} title="Natural draft" onApply={onApplyPreview} onSave={(preview) => savePreview(preview, 'Natural AI Draft')} saving={loadingAction === 'save'} />
        </section>

        <section className="doc-ai-section">
          <h3>Pack Advisor</h3>
          <label className="doc-ai-field"><span>What do you need this document pack for?</span><textarea aria-label="Document pack objective" value={objective} onChange={(event) => setObjective(event.target.value)} placeholder="For example: Prepare our company for corporate bank onboarding." /></label>
          <button type="button" onClick={analyze} disabled={!objective.trim() || loadingAction}>{loadingAction === 'advisor' ? 'Analyzing…' : 'Analyze Required Documents'}</button>
          {advisor && <div className="doc-ai-recommendations"><div className="doc-ai-readiness">Readiness: {Math.round((advisor.profile_validation?.completeness_ratio || 0) * 100)}%</div>{recommendations.length === 0 && <p className="doc-ai-empty">No recommendations returned.</p>}{recommendations.map((item) => <label key={item.document_type} className={`doc-ai-recommendation ${item.priority}`}><input type="checkbox" checked={selectedTypes.includes(item.document_type)} onChange={() => toggleType(item.document_type)} /><span><strong>{item.title}</strong><em>{item.priority === 'required' ? 'Required' : 'Optional'}</em><small>{item.reason}</small>{item.missing_data?.length > 0 && <span className="doc-ai-missing"><AlertTriangle size={13} />Missing: {item.missing_data.join(', ')}</span>}</span></label>)}{recommendations.length > 0 && <div className="doc-ai-selection-actions"><button type="button" onClick={() => setSelectedTypes([...new Set(requiredTypes)])}>Select required</button><button type="button" onClick={() => setSelectedTypes([...new Set(recommendations.map((item) => item.document_type))])}>Select all recommendations</button></div>}</div>}
        </section>

        <section className="doc-ai-section">
          <h3>Validated generation</h3>
          <label className="doc-ai-field"><span>Document type</span><select aria-label="AI document type" value={documentType} onChange={(event) => setDocumentType(event.target.value)}>{documentTypes.map((type) => <option key={type} value={type}>{type.replaceAll('_', ' ')}</option>)}</select></label>
          <ProviderSelect value={provider} onChange={setProvider} />
          <ProviderSelect value={fallbackProvider} onChange={setFallbackProvider} label="Explicit fallback" />
          <button type="button" onClick={createAIPreview} disabled={!objective.trim() || loadingAction}>{loadingAction === 'generation' ? 'Generating preview…' : 'Generate AI Preview'}</button>
          <PreviewCard preview={aiPreview} title="AI draft" onApply={onApplyPreview} onSave={(preview) => savePreview(preview, documentType.replaceAll('_', ' '))} saving={loadingAction === 'save'} />
        </section>

        <section className="doc-ai-section">
          <h3>Selected pack preview</h3>
          <p>{selectedTypes.length} document type{selectedTypes.length === 1 ? '' : 's'} selected.</p>
          <button type="button" onClick={createPackPreview} disabled={!objective.trim() || selectedTypes.length === 0 || loadingAction}>{loadingAction === 'pack' ? 'Generating pack preview…' : 'Preview Selected'}</button>
          {packPreview && <div className="doc-ai-pack-results" aria-label="Pack preview results"><div className={`doc-ai-pack-summary ${packPreview.overall_status}`}>{packPreview.overall_status === 'complete' ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}Overall status: {String(packPreview.overall_status || '').replaceAll('_', ' ')}</div>{(packPreview.items || []).map((item, index) => <div key={`${item.document_type}-${index}`} className={`doc-ai-pack-item ${item.status}`}><FileText size={15} /><span><strong>{item.document_type.replaceAll('_', ' ')}</strong><small>{item.error_message || item.status}</small></span>{item.preview && <><button type="button" onClick={() => onApplyPreview(item.preview)}>Review and apply</button><button type="button" onClick={() => savePreview(item.preview, item.document_type.replaceAll('_', ' '))} disabled={loadingAction === 'save'}>Save</button></>}</div>)}{(packPreview.items || []).some((item) => item.preview && item.status !== 'failed') && <button type="button" className="doc-ai-apply" onClick={savePack} disabled={loadingAction === 'save-pack'}><Save size={14} /> {loadingAction === 'save-pack' ? 'Saving pack…' : 'Save Ready Pack to Library'}</button>}</div>}
        </section>
      </div>
    </aside>
  );
}
