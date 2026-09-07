import React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import IdentityPacks from './IdentityPacks';
import { apiDelete, apiGet, uploadFormData } from '../lib/api';
import { toast } from 'sonner';

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

  it('selects, deselects, and selects all packs without changing the active pack', async () => {
    apiGet.mockResolvedValue([alpha, beta]);
    await act(async () => { root.render(<IdentityPacks />); await flush(); });

    const alphaCheckbox = host.querySelector('[data-testid="select-pack-alpha"]');
    const betaCheckbox = host.querySelector('[data-testid="select-pack-beta"]');
    await act(async () => { alphaCheckbox.click(); await flush(); });
    expect(alphaCheckbox.checked).toBe(true);
    expect(host.textContent).toContain('1 selected');

    await act(async () => { betaCheckbox.click(); await flush(); });
    expect(host.textContent).toContain('2 selected');
    await act(async () => { alphaCheckbox.click(); await flush(); });
    expect(host.textContent).toContain('1 selected');
    expect(betaCheckbox.checked).toBe(true);

    await act(async () => { host.querySelector('[data-testid="select-all-packs"]').click(); await flush(); });
    expect(host.querySelector('[data-testid="select-pack-alpha"]').checked).toBe(true);
    expect(host.querySelector('[data-testid="select-pack-beta"]').checked).toBe(true);
    expect(host.textContent).toContain('2 selected');
    await act(async () => { host.querySelector('[data-testid="select-all-packs"]').click(); await flush(); });
    expect(host.querySelector('[data-testid="select-pack-alpha"]').checked).toBe(false);
    expect(host.querySelector('[data-testid="select-pack-beta"]').checked).toBe(false);
  });

  it('requires confirmation and never deletes a non-selected pack', async () => {
    apiGet.mockResolvedValue([alpha, beta]);
    apiDelete.mockResolvedValue({});
    window.confirm.mockReturnValueOnce(false).mockReturnValueOnce(true);
    await act(async () => { root.render(<IdentityPacks />); await flush(); });
    await act(async () => { host.querySelector('[data-testid="select-pack-alpha"]').click(); await flush(); });

    await act(async () => { host.querySelector('[data-testid="delete-selected-packs"]').click(); await flush(); });
    expect(apiDelete).not.toHaveBeenCalled();

    await act(async () => { host.querySelector('[data-testid="delete-selected-packs"]').click(); await flush(); });
    expect(window.confirm).toHaveBeenLastCalledWith('Permanently delete 1 selected Identity Pack and their photos?');
    expect(apiDelete).toHaveBeenCalledTimes(1);
    expect(apiDelete).toHaveBeenCalledWith('/identity-packs/alpha');
    expect(apiDelete).not.toHaveBeenCalledWith('/identity-packs/beta');
  });

  it('deletes all explicitly selected packs and refreshes the list', async () => {
    apiGet.mockResolvedValueOnce([alpha, beta]).mockResolvedValueOnce([]);
    apiDelete.mockResolvedValue({});
    await act(async () => { root.render(<IdentityPacks />); await flush(); });
    await act(async () => { host.querySelector('[data-testid="select-all-packs"]').click(); await flush(); });
    await act(async () => { host.querySelector('[data-testid="delete-selected-packs"]').click(); await flush(); });

    expect(window.confirm).toHaveBeenCalledWith('Permanently delete 2 selected Identity Packs and their photos?');
    expect(apiDelete).toHaveBeenCalledWith('/identity-packs/alpha');
    expect(apiDelete).toHaveBeenCalledWith('/identity-packs/beta');
    expect(host.querySelector('[data-testid="pack-item-alpha"]')).toBeNull();
    expect(host.querySelector('[data-testid="pack-item-beta"]')).toBeNull();
    expect(host.textContent).toContain('Deleted 2 Identity Packs.');
  });

  it('preserves failed packs and reports partial deletion failures', async () => {
    apiGet.mockResolvedValueOnce([alpha, beta]).mockResolvedValueOnce([beta]);
    apiDelete.mockImplementation((path) => path.endsWith('/alpha') ? Promise.resolve({}) : Promise.reject(new Error('Delete failed')));
    await act(async () => { root.render(<IdentityPacks />); await flush(); });
    await act(async () => { host.querySelector('[data-testid="select-all-packs"]').click(); await flush(); });
    await act(async () => { host.querySelector('[data-testid="delete-selected-packs"]').click(); await flush(); });

    expect(host.querySelector('[data-testid="pack-item-alpha"]')).toBeNull();
    expect(host.querySelector('[data-testid="pack-item-beta"]')).not.toBeNull();
    expect(host.querySelector('[data-testid="select-pack-beta"]').checked).toBe(true);
    expect(host.querySelector('[data-testid="bulk-delete-result"]')?.textContent).toContain('1 could not be deleted');
  });

  it('reports the fifteen-reference capacity in the pack detail', async () => {
    const fullPack = { ...alpha, photo_ids: Array.from({ length: 15 }, (_, index) => 'photo-' + index), primary_photo_id: 'photo-0' };
    apiGet.mockResolvedValue([fullPack]);
    await act(async () => { root.render(<IdentityPacks />); await flush(); });
    expect(host.textContent).toContain('15 of 15 reference photographs');
    expect(host.textContent).toContain('15 / 15 refs');
  });

  it('rejects a multi-file upload that exceeds the remaining capacity before calling the API', async () => {
    const packWithTwelve = { ...alpha, photo_ids: Array.from({ length: 12 }, (_, index) => 'photo-' + index), primary_photo_id: 'photo-0' };
    apiGet.mockResolvedValue([packWithTwelve]);
    await act(async () => { root.render(<IdentityPacks />); await flush(); });
    const input = host.querySelector('[data-testid="upload-input"]');
    const files = Array.from({ length: 4 }, (_, index) => new File(['image-' + index], 'face-' + index + '.png', { type: 'image/png' }));
    Object.defineProperty(input, 'files', { configurable: true, value: files });
    await act(async () => { input.dispatchEvent(new Event('change', { bubbles: true })); await flush(); });
    expect(uploadFormData).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith('Only 3 more reference photos can be added to this Identity Pack.');
  });

});