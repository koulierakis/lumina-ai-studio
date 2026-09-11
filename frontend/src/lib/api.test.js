import { api } from './api';

describe('api 401 session handling', () => {
  test('clears cached authentication when the server returns 401', async () => {
    window.history.replaceState({}, '', '/login');
    localStorage.setItem('lumina_token', 'expired-token');
    localStorage.setItem('lumina_user', JSON.stringify({ email: 'owner@example.com' }));

    const responseHandler = api.interceptors.response.handlers[0];
    const error = { response: { status: 401 } };

    await expect(responseHandler.rejected(error)).rejects.toBe(error);
    expect(localStorage.getItem('lumina_token')).toBeNull();
    expect(localStorage.getItem('lumina_user')).toBeNull();
  });
});
