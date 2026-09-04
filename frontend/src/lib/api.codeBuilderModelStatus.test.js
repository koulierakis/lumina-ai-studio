import { api, apiGet } from './api';

describe('Code Builder model status routing', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  test('uses the Code Builder model-status endpoint directly', async () => {
    const response = {
      status: 'ready',
      model: 'qwen2.5-coder:7b',
      available: true,
      configured: true,
      message: 'Code Builder model is ready.',
    };
    const request = jest.spyOn(api, 'request').mockResolvedValue({ data: response });

    await expect(apiGet('/code-builder/model-status', { retry: false })).resolves.toEqual(response);
    expect(request).toHaveBeenCalledWith(expect.objectContaining({
      method: 'get',
      url: '/code-builder/model-status',
    }));
  });
});
