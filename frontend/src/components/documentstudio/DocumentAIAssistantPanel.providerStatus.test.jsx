import { act } from 'react';
import { createRoot } from 'react-dom/client';
import DocumentAIAssistantPanel from './DocumentAIAssistantPanel';
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

describe('DocumentAIAssistantPanel provider readiness', () => {
  let host;
  let root;

  beforeEach(() => {
    jest.clearAllMocks();
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
  });

  afterEach(() => {
    act(() => root.unmount());
    host.remove();
  });

  test('shows live Ollama readiness and selected model without removing CV builder', async () => {
    apiGet.mockResolvedValue({
      any_ready: true,
      providers: {
        ollama: { ready: true, selected_structured_document_model: 'qwen-test' },
        groq: { ready: false, error: 'not configured' },
      },
    });

    await act(async () => {
      root.render(
        <DocumentAIAssistantPanel
          profileId="profile-1"
          onApplyPreview={() => {}}
          onDocumentSaved={() => {}}
          onClose={() => {}}
        />,
      );
    });

    expect(apiGet).toHaveBeenCalledWith('/documents/ai/providers/status');
    expect(host.textContent).toContain('AI readiness');
    expect(host.textContent).toContain('Ollama · qwen-test · ready');
    expect(host.textContent).toContain('Groq · not configured');
    expect(host.textContent).toContain('Professional CV / Résumé');
  });
});
