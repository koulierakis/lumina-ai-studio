import React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import Login from './Login';
import { useAuth } from '../context/AuthContext';
import { toast } from 'sonner';

jest.mock('../context/AuthContext', () => ({
  useAuth: jest.fn(),
}));

jest.mock('react-router-dom', () => ({
  Navigate: () => null,
  useNavigate: () => jest.fn(),
}));

jest.mock('sonner', () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));

jest.mock('lucide-react', () => ({
  Sparkles: () => <span aria-hidden="true" />,
}));

describe('Login error handling', () => {
  let host;
  let root;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    jest.clearAllMocks();
    useAuth.mockReturnValue({
      user: null,
      ready: true,
      login: jest.fn().mockRejectedValue({
        response: {
          status: 401,
          data: {
            detail: {
              code: 'http_401',
              message: 'Authentication required',
              technical_details: { path: '/api/auth/login' },
              exception_type: 'HTTPException',
            },
          },
        },
      }),
    });
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
  });

  afterEach(() => {
    act(() => root.unmount());
    host.remove();
  });

  it('keeps the login page visible and renders structured 401 errors as text', async () => {
    await act(async () => {
      root.render(<Login />);
    });
    await act(async () => {
      host.querySelector('[data-testid="login-form"]').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });

    expect(host.querySelector('[data-testid="login-form"]')).not.toBeNull();
    expect(toast.error).toHaveBeenCalledWith('Authentication required');
    expect(typeof toast.error.mock.calls[0][0]).toBe('string');
  });
});
