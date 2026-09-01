import React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import IdentityPacks from './IdentityPacks';
import { apiDelete, apiGet } from '../lib/api';

jest.mock('../lib/api', () => ({
  apiDelete: jest.fn(() => Promise.resolve({})),
  apiGet: jest.fn(),
  apiPatch: jest.fn(),
  apiPost: jest.fn(),
  uploadFormData: jest.fn(),
}));

jest.mock('../components/AuthImage', () => () => <div data-testid="auth-image" />);
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn() } }));

const alpha = { id: 'alpha', name: 'Alpha', photo_ids: [], primary_photo_id: null };
const beta = { id: 'beta', name: 'Beta', photo_ids: [], primary_photo_id: null };

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
}

describe('Identity Packs recovery', () => {
  let host;
  let root;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    localStorage.clear();
    jest.clearAllMocks();
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
    window.confirm = jest.fn(() => true);
  });

  afterEach(() => {
    act(() => root.unmount());
    host.remove();
    localStorage.clear();
    jest.restoreAllMocks();
  });

  it('restores the previously active pack after reopening the page', async () => {
    localStorage.setItem('lumina_active_pack', 'beta');
    apiGet.mockResolvedValue([alpha, beta]);

    await act(async () => {
      root.render(<IdentityPacks />);
      await flush();
    });

    expect(host.querySelector('[data-testid="pack-detail-name"]')?.textContent).toBe('Beta');
    expect(localStorage.getItem('lumina_active_pack')).toBe('beta');
  });

  it('selects a remaining pack after deleting the active one', async () => {
    localStorage.setItem('lumina_active_pack', 'alpha');
    apiGet.mockResolvedValueOnce([alpha, beta]).mockResolvedValueOnce([beta]);
    apiDelete.mockResolvedValue({});

    await act(async () => {
      root.render(<IdentityPacks />);
      await flush();
    });
    expect(host.querySelector('[data-testid="pack-detail-name"]')?.textContent).toBe('Alpha');

    await act(async () => {
      host.querySelector('[data-testid="delete-pack-btn"]').click();
      await flush();
    });

    expect(apiDelete).toHaveBeenCalledWith('/identity-packs/alpha');
    expect(host.querySelector('[data-testid="pack-detail-name"]')?.textContent).toBe('Beta');
    expect(localStorage.getItem('lumina_active_pack')).toBe('beta');
  });

  it('shows a recoverable error instead of silently leaving the page empty', async () => {
    apiGet.mockRejectedValue({ message: 'Identity service unavailable.' });

    await act(async () => {
      root.render(<IdentityPacks />);
      await flush();
    });

    expect(host.querySelector('[role="alert"]')?.textContent).toContain('Identity service unavailable.');
    expect([...host.querySelectorAll('button')].some((button) => button.textContent === 'Retry')).toBe(true);
  });
});