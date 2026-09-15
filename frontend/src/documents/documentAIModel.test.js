import { apiPost } from '../lib/api';
import {
  DOCUMENT_AI_PROVIDERS,
  friendlyDocumentAIError,
  generateAIPreview,
  generatePackPreview,
  naturalCreatePreview,
  packAdvisor,
} from './model';

jest.mock('../lib/api', () => ({
  API_BASE: '/api',
  apiDelete: jest.fn(),
  apiGet: jest.fn(),
  apiPatch: jest.fn(),
  apiPost: jest.fn(),
  apiPut: jest.fn(),
  uploadFormData: jest.fn(),
}));

describe('Document Studio AI API client', () => {
  beforeEach(() => apiPost.mockReset().mockResolvedValue({}));

  test('uses the existing client for Pack Advisor and normalizes duplicates', async () => {
    apiPost.mockResolvedValue({
      recommendations: [
        { document_type: 'nda', priority: 'required' },
        { document_type: 'nda', priority: 'required' },
      ],
    });
    const result = await packAdvisor({ objective: '  Bank onboarding  ', company_profile_id: 'profile-1' });

    expect(apiPost).toHaveBeenCalledWith('/documents/pack-advisor', {
      objective: 'Bank onboarding',
      company_profile_id: 'profile-1',
    });
    expect(result.recommendations).toHaveLength(1);
  });

  test('sends natural preview without persistence or fallback flags', async () => {
    await naturalCreatePreview({ request: ' Draft an NDA ', provider: 'Ollama' });
    expect(apiPost).toHaveBeenCalledWith('/documents/natural-create/preview', expect.objectContaining({
      request: 'Draft an NDA',
      provider: 'ollama',
      allow_fallback: false,
    }));
  });

  test('sends typed AI generation preview and explicit fallback policy', async () => {
    await generateAIPreview({
      objective: 'Draft an NDA',
      document_type: 'nda',
      provider: 'ollama',
      fallback_provider: 'groq',
      allow_fallback: true,
    });
    expect(apiPost).toHaveBeenCalledWith('/documents/generate-ai/preview', expect.objectContaining({
      document_type: 'nda',
      provider: 'ollama',
      fallback_provider: 'groq',
      allow_fallback: true,
    }));
  });

  test('deduplicates selected pack types without enabling generate-all', async () => {
    await generatePackPreview({
      objective: 'Transaction pack',
      selected_document_types: ['nda', 'consulting_agreement', 'nda'],
    });
    expect(apiPost).toHaveBeenCalledWith('/documents/generate-pack/preview', expect.objectContaining({
      selected_document_types: ['nda', 'consulting_agreement'],
      generate_all: false,
    }));
  });

  test('allows only canonical provider identities before making a request', async () => {
    expect(DOCUMENT_AI_PROVIDERS).toEqual(['ollama', 'groq']);
    expect(() => generateAIPreview({ objective: 'Draft', document_type: 'nda', provider: 'plugin.path' }))
      .toThrow('Unsupported document AI provider.');
    expect(apiPost).not.toHaveBeenCalled();
  });

  test('normalizes provider and validation errors without exposing backend details', () => {
    expect(friendlyDocumentAIError({ status: 503, message: 'Authorization: secret' }))
      .toBe('The selected AI provider is unavailable.');
    expect(friendlyDocumentAIError({ status: 504 })).toBe('The AI provider timed out. Try again.');
    expect(friendlyDocumentAIError({ status: 422 })).toContain('fact-integrity');
  });
});
