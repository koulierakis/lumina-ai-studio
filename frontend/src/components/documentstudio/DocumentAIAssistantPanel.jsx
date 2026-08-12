import { useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, ChevronUp, FileText, Sparkles, XCircle } from 'lucide-react';
import {
  DOCUMENT_AI_PROVIDERS,
  documentApi,
  friendlyDocumentAIError,
} from '../../documents/model';

const DEFAULT_DOCUMENT_TYPES = [
  'nda',
  'consulting_agreement',
  'company_profile',
  'board_resolution',
  'corporate_resolution',
  'banking_cover_letter',
  'aml_declaration',
];

function ProviderSelect({ value, onChange, label = 'Provider' }) {
  return (
    <label className="doc-ai-field doc-ai-provider-field">
      <span>{label}</span>
      <select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">Automatic (Ollama)</option>
        {DOCUMENT_AI_PROVIDERS.map((provider) => (
          <option key={provider} value={provider}>{provider === 'groq' ? 'Groq' : 'Ollama'}</option>
        ))}
      </select>
    </label>
  );
}

function PreviewCard({ preview, title, onApply }) {
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
      <button type="button" className="doc-ai-apply" onClick={() => onApply(preview)}>
        Apply to Document
      </button>
    </section>
  );
}

export default function DocumentAIAssistantPanel({ profileId, onApplyPreview, onClose }) {
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
  const [loadingAction, setLoadingAction] = useState('');
  const [error, setError] = useState('');

  const recommendations = useMemo(() => advisor?.recommendations || [], [advisor?.recommendations]);
  const documentTypes = useMemo(() => [...new Set([
    ...recommendations.map((item) => item.document_type),
    ...DEFAULT_DOCUMENT_TYPES,
  ])], [recommendations]);
  const requiredTypes = recommendations
    .filter((item) => item.priority === 'required')
    .map((item) => item.document_type);

  function toggleType(type) {
    setSelectedTypes((current) => (
      current.includes(type) ? current.filter((item) => item !== type) : [...current, type]
    ));
  }

  async function run(action, operation) {
    setLoadingAction(action);
    setError('');
    try {
      return await operation();
    } catch (caught) {
      setError(friendlyDocumentAIError(caught));
      return null;
    } finally {
      setLoadingAction('');
    }
  }

  async function analyze() {
    const result = await run('advisor', () => documentApi.packAdvisor({
      objective,
      company_profile_id: profileId,
    }));
    if (!result) return;
    setAdvisor(result);
    setSelectedTypes([]);
    if (result.recommendations?.[0]?.document_type) {
      setDocumentType(result.recommendations[0].document_type);
    }
  }

  async function createNaturalPreview() {
    const result = await run('natural', () => documentApi.naturalCreatePreview({
      request: naturalRequest,
      company_profile_id: profileId,
      provider,
    }));
    if (result) setNaturalPreview(result);
  }

  async function createAIPreview() {
    const result = await run('generation', () => documentApi.generateAIPreview({
      objective,
      document_type: documentType,
      company_profile_id: profileId,
      provider,
      fallback_provider: fallbackProvider,
      allow_fallback: Boolean(fallbackProvider),
    }));
    if (result) setAIPreview(result);
  }

  async function createPackPreview() {
    const result = await run('pack', () => documentApi.generatePackPreview({
      objective,
      company_profile_id: profileId,
      selected_document_types: selectedTypes,
      provider,
      fallback_provider: fallbackProvider,
      allow_fallback: Boolean(fallbackProvider),
    }));
    if (result) setPackPreview(result);
  }

  return (
    <aside className="doc-ai-panel" aria-label="AI document assistance">
      <div className="doc-ai-panel-header">
        <div><Sparkles size={18} /><strong>AI Assistance</strong><span>Preview before applying</span></div>
        <button type="button" onClick={onClose} aria-label="Close AI assistance"><ChevronUp size={18} /></button>
      </div>

      {error && <div className="doc-ai-error" role="alert"><XCircle size={16} />{error}</div>}

      <div className="doc-ai-grid">
        <section className="doc-ai-section">
          <h3>Pack Advisor</h3>
          <label className="doc-ai-field">
            <span>What do you need this document pack for?</span>
            <textarea
              aria-label="Document pack objective"
              value={objective}
              onChange={(event) => setObjective(event.target.value)}
              placeholder="For example: Prepare our company for corporate bank onboarding."
            />
          </label>
          <button type="button" onClick={analyze} disabled={!objective.trim() || loadingAction}>
            {loadingAction === 'advisor' ? 'Analyzing…' : 'Analyze Required Documents'}
          </button>
          {advisor && (
            <div className="doc-ai-recommendations">
              <div className="doc-ai-readiness">
                Readiness: {Math.round((advisor.profile_validation?.completeness_ratio || 0) * 100)}%
              </div>
              {recommendations.length === 0 && <p className="doc-ai-empty">No recommendations returned.</p>}
              {recommendations.map((item) => (
                <label key={item.document_type} className={`doc-ai-recommendation ${item.priority}`}>
                  <input
                    type="checkbox"
                    checked={selectedTypes.includes(item.document_type)}
                    onChange={() => toggleType(item.document_type)}
                  />
                  <span>
                    <strong>{item.title}</strong>
                    <em>{item.priority === 'required' ? 'Required' : 'Optional'}</em>
                    <small>{item.reason}</small>
                    {item.missing_data?.length > 0 && (
                      <span className="doc-ai-missing"><AlertTriangle size={13} />Missing: {item.missing_data.join(', ')}</span>
                    )}
                  </span>
                </label>
              ))}
              {recommendations.length > 0 && (
                <div className="doc-ai-selection-actions">
                  <button type="button" onClick={() => setSelectedTypes([...new Set(requiredTypes)])}>Select required</button>
                  <button type="button" onClick={() => setSelectedTypes([...new Set(recommendations.map((item) => item.document_type))])}>Select all recommendations</button>
                </div>
              )}
            </div>
          )}
        </section>

        <section className="doc-ai-section">
          <h3>Natural creation</h3>
          <label className="doc-ai-field">
            <span>Describe the document</span>
            <textarea
              aria-label="Natural document request"
              value={naturalRequest}
              onChange={(event) => setNaturalRequest(event.target.value)}
              placeholder="Create a corporate banking business nature statement."
            />
          </label>
          <ProviderSelect value={provider} onChange={setProvider} />
          <button type="button" onClick={createNaturalPreview} disabled={!naturalRequest.trim() || loadingAction}>
            {loadingAction === 'natural' ? 'Creating preview…' : 'Preview Natural Draft'}
          </button>
          <PreviewCard preview={naturalPreview} title="Natural draft" onApply={onApplyPreview} />
        </section>

        <section className="doc-ai-section">
          <h3>Validated generation</h3>
          <label className="doc-ai-field">
            <span>Document type</span>
            <select aria-label="AI document type" value={documentType} onChange={(event) => setDocumentType(event.target.value)}>
              {documentTypes.map((type) => <option key={type} value={type}>{type.replaceAll('_', ' ')}</option>)}
            </select>
          </label>
          <ProviderSelect value={provider} onChange={setProvider} />
          <ProviderSelect value={fallbackProvider} onChange={setFallbackProvider} label="Explicit fallback" />
          <button type="button" onClick={createAIPreview} disabled={!objective.trim() || loadingAction}>
            {loadingAction === 'generation' ? 'Generating preview…' : 'Generate AI Preview'}
          </button>
          <PreviewCard preview={aiPreview} title="AI draft" onApply={onApplyPreview} />
        </section>

        <section className="doc-ai-section">
          <h3>Selected pack preview</h3>
          <p>{selectedTypes.length} document type{selectedTypes.length === 1 ? '' : 's'} selected.</p>
          <button type="button" onClick={createPackPreview} disabled={!objective.trim() || selectedTypes.length === 0 || loadingAction}>
            {loadingAction === 'pack' ? 'Generating pack preview…' : 'Preview Selected'}
          </button>
          {packPreview && (
            <div className="doc-ai-pack-results" aria-label="Pack preview results">
              <div className={`doc-ai-pack-summary ${packPreview.overall_status}`}>
                {packPreview.overall_status === 'complete' ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
                Overall status: {String(packPreview.overall_status || '').replaceAll('_', ' ')}
              </div>
              {(packPreview.items || []).map((item, index) => (
                <div key={`${item.document_type}-${index}`} className={`doc-ai-pack-item ${item.status}`}>
                  <FileText size={15} />
                  <span><strong>{item.document_type.replaceAll('_', ' ')}</strong><small>{item.error_message || item.status}</small></span>
                  {item.preview && <button type="button" onClick={() => onApplyPreview(item.preview)}>Review and apply</button>}
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </aside>
  );
}
