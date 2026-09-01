import React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import WorkspaceCenter, { readRecentSearches } from './WorkspaceCenter';

jest.mock('../lib/api', () => ({
  apiDelete: jest.fn(),
  apiGet: jest.fn(),
  apiPatch: jest.fn(),
  apiPost: jest.fn(),
  apiPut: jest.fn(),
}));

describe('Workspace search recovery', () => {
  let host;
  let root;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    localStorage.clear();
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
  });

  afterEach(() => {
    act(() => root.unmount());
    host.remove();
    localStorage.clear();
    jest.restoreAllMocks();
  });

  it('falls back to an empty history when saved search data is corrupted', async () => {
    localStorage.setItem('lumina_recent_searches', '{broken');
    expect(readRecentSearches()).toEqual([]);

    await act(async () => {
      root.render(
        <MemoryRouter>
          <WorkspaceCenter mode="search" />
        </MemoryRouter>,
      );
    });

    expect(host.textContent).toContain('Search everything');
    expect(host.textContent).not.toContain('Recent:');
  });

  it('keeps only valid recent search text and caps the list at five entries', () => {
    localStorage.setItem('lumina_recent_searches', JSON.stringify(['one', 2, '', 'two', 'three', 'four', 'five', 'six']));
    expect(readRecentSearches()).toEqual(['one', 'two', 'three', 'four', 'five']);
  });
});