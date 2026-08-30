import fs from 'fs';
import path from 'path';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import DocumentAIAssistantPanel from './DocumentAIAssistantPanel';
import { documentApi } from '../../documents/model';
import { apiGet } from '../../lib/api';

jest.mock('../../documents/model', () => ({
  DOCUMENT_AI_PROVIDERS: ['ollama', 'groq'],
  documentApi: {
    packAdvisor: jest.fn(),
    naturalCreatePreview: jest.fn(),
    generateAIPreview: jest.fn(),
    generatePackPreview: jest.fn(),
    create: jest.fn(),
  },
  friendlyDocumentAIError: (error) => error?.message || 'AI request failed.',
}));

jest.mock('../../lib/api', () => ({
  apiGet: jest.fn(),
}));

function clickByText(container, text) {
  const button = [...container.querySelectorAll('button')].find((item) => item.textContent.includes(text));
  if (!button) throw new Error(`Button not found: ${text}`);
  button.dispatchEvent(new MouseEvent('click', { bubbles: true }));
}

function setValue(element, value) {
  const setter = Object.getOwnPropertyDescriptor(element.constructor.prototype, 'value').set;
  setter.call(element, value);
  element.dispatchEvent(new Event('input', { bubbles: true }));
  element.dispatchEvent(new Event('change', { bubbles: true }));
}

describe('DocumentAIAssistantPanel', () => {
  let host;
  let root;
  const onApplyPreview = jest.fn();
  const onDocumentSaved = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    apiGet.mockResolvedValue({
      default_provider: 'ollama',
      any_ready: true,
      providers: {
        ollama: { available: true, ready: true, selected_document_model: 'qwen2.5-coder:7b' },
        groq: { available: false, ready: false, error: 'Not configured' },
      },
    });
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
  });

  afterEach(() => {
    act(() => root.unmount());
    host.remove();
  });

  async function renderPanel() {
    await act(async () => {
      root.render(<DocumentAIAssistantPanel profileId="profile-1" onApplyPreview={onApplyPreview} onDocumentSaved={onDocumentSaved} onClose={() => {}} />);
    });
  }

  test('shows provider readiness before generation', async () => {
    await renderPanel();

    expect(apiGet).toHaveBeenCalledWith('/documents/ai/providers/status');
    expect(host.textContent).toContain('Ollama · qwen2.5-coder:7b · ready');
    expect(host.textContent).toContain('Groq · Not configured');
  });

  test('natural creation is preview-first and only applies after explicit user action', async () => {
    const preview = { document: { title: 'Business Nature', document_type: 'business_nature_statement', content_text: 'Draft content' }, generation: { metadata: { provider_used: 'ollama', validation_status: 'validated' } } };
    documentApi.naturalCreatePreview.mockResolvedValue(preview);
    await renderPanel();
    await act(async () => setValue(host.querySelector('[aria-label="Natural document request"]'), 'Create a business nature statement'));
    await act(async () => clickByText(host, 'Preview Natural Draft'));
    expect(documentApi.naturalCreatePreview).toHaveBeenCalledWith(expect.objectContaining({ request: 'Create a business nature statement', company_profile_id: 'profile-1' }));
    expect(onApplyPreview).not.toHaveBeenCalled();
    expect(host.textContent).toContain('Preview only');
    await act(async () => clickByText(host, 'Apply to Current Document'));
    expect(onApplyPreview).toHaveBeenCalledWith(preview);
  });

  test('validated generation preserves explicit provider and fallback controls', async () => {
    const preview = { document: { title: 'NDA', document_type: 'nda', content_text: 'NDA draft' }, generation: { metadata: { provider_used: 'groq', validation_status: 'validated' } } };
    documentApi.generateAIPreview.mockResolvedValue(preview);
    await renderPanel();
    await act(async () => setValue(host.querySelector('[aria-label="Document pack objective"]'), 'Prepare an NDA'));
    await act(async () => setValue(host.querySelector('[aria-label="Provider"]'), 'groq'));
    await act(async () => setValue(host.querySelector('[aria-label="Explicit fallback"]'), 'ollama'));
    await act(async () => clickByText(host, 'Generate AI Preview'));
    expect(documentApi.generateAIPreview).toHaveBeenCalledWith(expect.objectContaining({ objective: 'Prepare an NDA', provider: 'groq', fallback_provider: 'ollama', allow_fallback: true }));
    expect(host.textContent).toContain('Provider: groq');
  });

  test('saved AI preview becomes a library document and notifies the parent', async () => {
    const preview = { document: { title: 'NDA', document_type: 'nda', content_text: 'NDA draft' }, generation: { metadata: { provider_used: 'ollama' } } };
    const created = { id: 'doc-1', title: 'NDA' };
    documentApi.generateAIPreview.mockResolvedValue(preview);
    documentApi.create.mockResolvedValue(created);
    await renderPanel();
    await act(async () => setValue(host.querySelector('[aria-label="Document pack objective"]'), 'Prepare an NDA'));
    await act(async () => clickByText(host, 'Generate AI Preview'));
    await act(async () => clickByText(host, 'Save as New Document'));
    expect(documentApi.create).toHaveBeenCalledWith(expect.objectContaining({ title: 'NDA', document_type: 'nda', company_profile_id: 'profile-1' }));
    expect(onDocumentSaved).toHaveBeenCalledWith(created);
  });

  test('pack advisor exposes missing-data warnings and selection controls', async () => {
    documentApi.packAdvisor.mockResolvedValue({
      profile_validation: { completeness_ratio: 0.5 },
      recommendations: [
        { document_type: 'nda', title: 'NDA', priority: 'required', reason: 'Protect confidentiality', missing_data: ['legal_name'] },
        { document_type: 'consulting_agreement', title: 'Consulting Agreement', priority: 'optional', reason: 'Define scope', missing_data: [] },
      ],
    });
    await renderPanel();
    await act(async () => setValue(host.querySelector('[aria-label="Document pack objective"]'), 'Prepare agreements'));
    await act(async () => clickByText(host, 'Analyze Required Documents'));
    expect(host.textContent).toContain('Readiness: 50%');
    expect(host.textContent).toContain('Missing: legal_name');
    await act(async () => clickByText(host, 'Select required'));
    expect([...host.querySelectorAll('input[type="checkbox"]')].filter((item) => item.checked)).toHaveLength(1);
  });

  test('pack preview keeps partial failures visible instead of silently saving them', async () => {
    documentApi.packAdvisor.mockResolvedValue({
      profile_validation: { completeness_ratio: 1 },
      recommendations: [
        { document_type: 'nda', title: 'NDA', priority: 'required', reason: 'Protect confidentiality', missing_data: [] },
        { document_type: 'consulting_agreement', title: 'Consulting Agreement', priority: 'required', reason: 'Define scope', missing_data: [] },
      ],
    });
    documentApi.generatePackPreview.mockResolvedValue({
      overall_status: 'partial_failure',
      items: [
        { document_type: 'nda', status: 'ready', preview: { document: { title: 'NDA', document_type: 'nda', content_text: 'Draft' } } },
        { document_type: 'consulting_agreement', status: 'failed', error_message: 'The provider is unavailable' },
      ],
    });
    await renderPanel();
    await act(async () => setValue(host.querySelector('[aria-label="Document pack objective"]'), 'Prepare agreements'));
    await act(async () => clickByText(host, 'Analyze Required Documents'));
    await act(async () => clickByText(host, 'Select all recommendations'));
    await act(async () => clickByText(host, 'Preview Selected'));

    const items = [...host.querySelectorAll('.doc-ai-pack-item')];
    expect(items.map((item) => item.textContent)).toEqual([
      expect.stringContaining('nda'),
      expect.stringContaining('consulting agreement'),
    ]);
    expect(host.textContent).toContain('Overall status: partial failure');
    expect(host.textContent).toContain('The provider is unavailable');
  });

  test('active page remains the editor-first component with legacy controls', () => {
    const page = fs.readFileSync(path.join(__dirname, '../../pages/DocumentStudio.jsx'), 'utf8');
    const panel = fs.readFileSync(path.join(__dirname, 'DocumentAIAssistantPanel.jsx'), 'utf8');
    const app = fs.readFileSync(path.join(__dirname, '../../App.js'), 'utf8');
    expect(app).toContain('import DocumentStudio from \'./pages/DocumentStudio\'');
    expect(app).toContain('<Route path="documents" element={<DocumentStudio />} />');
    expect(page).toContain('<DocumentRichEditor');
    expect(page).toContain('Import Word');
    expect(page).toContain('Export PDF');
    expect(page).toContain('Export Word');
    expect(page).toContain('doc-preset-btn');
    expect(page).toContain('applyAIPreview');
    expect(panel).toContain('Apply to Current Document');
    expect(page).not.toContain('h-screen');
    expect(page).not.toContain('overflow-hidden');
  });
});