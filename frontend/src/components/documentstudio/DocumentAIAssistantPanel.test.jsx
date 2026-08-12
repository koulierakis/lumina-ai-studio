import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import fs from 'fs';
import path from 'path';
import DocumentAIAssistantPanel from './DocumentAIAssistantPanel';
import { documentApi } from '../../documents/model';

jest.mock('lucide-react', () => new Proxy({}, {
  get: (_, name) => (props) => <span data-icon={String(name)} {...props} />,
}));

function setValue(element, value) {
  const setter = Object.getOwnPropertyDescriptor(element.constructor.prototype, 'value').set;
  setter.call(element, value);
  element.dispatchEvent(new Event('input', { bubbles: true }));
}

function clickByText(host, text) {
  const button = [...host.querySelectorAll('button')].find((item) => item.textContent.includes(text));
  if (!button) throw new Error(`Button not found: ${text}`);
  button.click();
}

describe('Document Studio AI assistance panel', () => {
  let host;
  let root;
  let onApplyPreview;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
    onApplyPreview = jest.fn();
    jest.spyOn(documentApi, 'packAdvisor').mockResolvedValue({ recommendations: [], profile_validation: {} });
    jest.spyOn(documentApi, 'naturalCreatePreview').mockResolvedValue({});
    jest.spyOn(documentApi, 'generateAIPreview').mockResolvedValue({});
    jest.spyOn(documentApi, 'generatePackPreview').mockResolvedValue({});
  });

  afterEach(() => {
    act(() => root.unmount());
    host.remove();
    jest.restoreAllMocks();
  });

  async function renderPanel() {
    await act(async () => root.render(
      <DocumentAIAssistantPanel profileId="profile-1" onApplyPreview={onApplyPreview} onClose={jest.fn()} />
    ));
  }

  test('renders objective, required/optional recommendations, warnings, and stable selection', async () => {
    documentApi.packAdvisor.mockResolvedValue({
      profile_validation: { completeness_ratio: 0.5 },
      recommendations: [
        { document_type: 'nda', title: 'NDA', priority: 'required', reason: 'Protects disclosures.', missing_data: ['UBO information'] },
        { document_type: 'company_profile', title: 'Company Profile', priority: 'optional', reason: 'Provides context.', missing_data: [] },
      ],
    });
    await renderPanel();
    await act(async () => setValue(host.querySelector('[aria-label="Document pack objective"]'), 'Bank onboarding'));
    await act(async () => clickByText(host, 'Analyze Required Documents'));

    expect(host.textContent).toContain('Required');
    expect(host.textContent).toContain('Optional');
    expect(host.textContent).toContain('Missing: UBO information');
    expect(host.textContent).toContain('Readiness: 50%');
    await act(async () => clickByText(host, 'Select all recommendations'));
    expect([...host.querySelectorAll('.doc-ai-recommendation input:checked')]).toHaveLength(2);
  });

  test('renders an explicit empty recommendation state', async () => {
    await renderPanel();
    await act(async () => setValue(host.querySelector('[aria-label="Document pack objective"]'), 'Unusual objective'));
    await act(async () => clickByText(host, 'Analyze Required Documents'));
    expect(host.textContent).toContain('No recommendations returned.');
  });

  test('natural preview never applies automatically and requires explicit apply', async () => {
    const preview = { document: { title: 'Business Nature', content: 'Preview content' } };
    documentApi.naturalCreatePreview.mockResolvedValue(preview);
    await renderPanel();
    await act(async () => setValue(host.querySelector('[aria-label="Natural document request"]'), 'Create a business nature statement'));
    await act(async () => clickByText(host, 'Preview Natural Draft'));

    expect(host.textContent).toContain('Preview content');
    expect(onApplyPreview).not.toHaveBeenCalled();
    await act(async () => clickByText(host, 'Apply to Document'));
    expect(onApplyPreview).toHaveBeenCalledWith(preview);
  });

  test('shows safe provider unavailable, timeout, and fact-integrity errors', async () => {
    await renderPanel();
    const request = host.querySelector('[aria-label="Natural document request"]');
    await act(async () => setValue(request, 'Create an NDA'));

    documentApi.naturalCreatePreview.mockRejectedValueOnce({ status: 503, message: 'secret' });
    await act(async () => clickByText(host, 'Preview Natural Draft'));
    expect(host.textContent).toContain('provider is unavailable');
    expect(host.textContent).not.toContain('secret');

    documentApi.naturalCreatePreview.mockRejectedValueOnce({ status: 504 });
    await act(async () => clickByText(host, 'Preview Natural Draft'));
    expect(host.textContent).toContain('timed out');

    documentApi.naturalCreatePreview.mockRejectedValueOnce({ status: 422 });
    await act(async () => clickByText(host, 'Preview Natural Draft'));
    expect(host.textContent).toContain('fact-integrity');
  });

  test('provider controls contain no arbitrary free-text option', async () => {
    await renderPanel();
    const providerSelects = [...host.querySelectorAll('select[aria-label="Provider"]')];
    expect(providerSelects.length).toBeGreaterThan(0);
    providerSelects.forEach((select) => {
      expect([...select.options].map((option) => option.value)).toEqual(['', 'ollama', 'groq']);
    });
  });

  test('shows validated metadata, fallback use, and retained placeholders', async () => {
    documentApi.generateAIPreview.mockResolvedValue({
      document: { title: 'NDA', content_text: 'Draft [CLIENT]' },
      generation: { metadata: { provider_used: 'groq', validation_status: 'passed', fallback_used: true } },
      intentional_blank_fields: ['CLIENT'],
    });
    await renderPanel();
    await act(async () => setValue(host.querySelector('[aria-label="Document pack objective"]'), 'Create an NDA'));
    await act(async () => clickByText(host, 'Generate AI Preview'));
    expect(host.textContent).toContain('Provider: groq');
    expect(host.textContent).toContain('Validation: passed');
    expect(host.textContent).toContain('Fallback used');
    expect(host.textContent).toContain('Placeholders retained: CLIENT');
  });

  test('pack preview preserves order and keeps partial failures visible', async () => {
    documentApi.packAdvisor.mockResolvedValue({
      profile_validation: { completeness_ratio: 1 },
      recommendations: [
        { document_type: 'nda', title: 'NDA', priority: 'required', reason: 'Required', missing_data: [] },
        { document_type: 'consulting_agreement', title: 'Consulting', priority: 'optional', reason: 'Useful', missing_data: [] },
      ],
    });
    documentApi.generatePackPreview.mockResolvedValue({
      overall_status: 'partial_failure',
      items: [
        { document_type: 'nda', status: 'failed', error_message: 'The provider is unavailable' },
        { document_type: 'consulting_agreement', status: 'generated', preview: { document: { content_html: '<p>Draft</p>' } } },
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
    expect(panel).toContain('Apply to Document');
    expect(page).not.toContain('h-screen');
    expect(page).not.toContain('overflow-hidden');
  });
});
