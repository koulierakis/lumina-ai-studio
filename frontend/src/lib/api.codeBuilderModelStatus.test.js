import { api, apiGet } from './api';

describe('Code Builder model status bridge', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  test('maps a reachable Ollama with the configured model to ready', async () => {
    const request = jest.spyOn(api, 'request').mockResolvedValue({
      data: {
        online: true,
        model: 'qwen2.5-coder:7b',
        installed: true,
        models: ['qwen2.5-coder:1.5b', 'qwen2.5-coder:7b'],
      },
    });

    await expect(apiGet('/code-builder/model-status', { retry: false })).resolves.toEqual({
      status: 'ready',
      model: 'qwen2.5-coder:7b',
      installed_models: ['qwen2.5-coder:1.5b', 'qwen2.5-coder:7b'],
    });
    expect(request).toHaveBeenCalledWith(expect.objectContaining({
      method: 'get',
      url: '/code-creator/status',
    }));
  });

  test('maps an unreachable Ollama to offline', async () => {
    jest.spyOn(api, 'request').mockResolvedValue({
      data: {
        online: false,
        model: 'qwen2.5-coder:7b',
        installed: false,
        models: [],
      },
    });

    await expect(apiGet('/code-builder/model-status', { retry: false })).resolves.toEqual({
      status: 'offline',
      model: 'qwen2.5-coder:7b',
      installed_models: [],
    });
  });

  test('maps a reachable Ollama with a missing configured model to not configured', async () => {
    jest.spyOn(api, 'request').mockResolvedValue({
      data: {
        online: true,
        model: 'qwen2.5-coder:7b',
        installed: false,
        models: ['qwen2.5-coder:1.5b'],
      },
    });

    await expect(apiGet('/code-builder/model-status', { retry: false })).resolves.toEqual({
      status: 'not_configured',
      model: 'qwen2.5-coder:7b',
      installed_models: ['qwen2.5-coder:1.5b'],
    });
  });
});
