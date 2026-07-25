import React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MODES, OrganizationActions } from './VideoStudio';

jest.mock('../lib/api', () => ({ apiPost: jest.fn(() => Promise.resolve({})), apiPatch: jest.fn(() => Promise.resolve({})) }));

describe('Video Studio regression surface', () => {
  let host; let root;
  beforeEach(() => { globalThis.IS_REACT_ACT_ENVIRONMENT = true; host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host); window.prompt = jest.fn(() => 'New item'); });
  afterEach(() => { act(() => root.unmount()); host.remove(); jest.restoreAllMocks(); });

  it('publishes all supported generation modes for capability filtering', () => {
    expect(MODES.map(([id]) => id)).toEqual(expect.arrayContaining(['text-to-video', 'image-to-video', 'multi-image', 'variation', 'extend', 'interpolation']));
  });

  it('creates and assigns folders and multi-membership collections through real API callbacks', async () => {
    const refresh = jest.fn(); const patch = jest.fn();
    await act(async () => root.render(<OrganizationActions selected={{ id: 'job-1', collection_ids: ['a'] }} facets={{ folders: [{ id: 'f', kind: 'folder', name: 'Client' }], collections: [{ id: 'b', kind: 'collection', name: 'Launch' }] }} onPatch={patch} onRefresh={refresh} />));
    const buttons = [...host.querySelectorAll('button')];
    await act(async () => buttons.find((x) => x.textContent === 'New folder').click());
    await act(async () => buttons.find((x) => x.textContent === 'Client').click());
    await act(async () => buttons.find((x) => x.textContent === 'Launch').click());
    expect(patch).toHaveBeenCalledWith(expect.objectContaining({ id: 'job-1' }), { folder: 'f' });
    expect(patch).toHaveBeenCalledWith(expect.objectContaining({ id: 'job-1' }), { collection_ids: ['a', 'b'] });
  });
});
