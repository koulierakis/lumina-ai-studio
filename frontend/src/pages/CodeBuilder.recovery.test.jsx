import React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import CodeBuilder from './CodeBuilder';
import { apiGet } from '../lib/api';

jest.mock('../lib/api', () => ({
  apiGet: jest.fn(),
  apiPost: jest.fn(),
}));

const restoredTask = {
  task_id: 'persisted-task',
  phase: 'awaiting_approval',
  instruction: 'Keep working after refresh',
  created_at_epoch: 1,
  updated_at_epoch: 2,
  preparation_result: null,
  review_result: null,
  result: null,
};

async function flushEffects() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

describe('Code Builder page recovery', () => {
  let host;
  let root;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    localStorage.clear();
    jest.clearAllMocks();
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

  it('reloads the remembered active task from the server instead of losing it', async () => {
    localStorage.setItem('lumina_code_builder_task_id', 'persisted-task');
    apiGet.mockImplementation((url) => {
      if (url === '/code-builder/model-status') return Promise.resolve({ status: 'ready' });
      if (url === '/code-builder/engines') return Promise.resolve({
        default: 'native',
        engines: [{ name: 'native', available: true, experimental: false, safe_mode: true }],
        openhands_ready: false,
      });
      if (url === '/code-builder/tasks/persisted-task') return Promise.resolve(restoredTask);
      if (url === '/code-builder/tasks?limit=50') return Promise.resolve({ items: [] });
      return Promise.resolve({});
    });

    await act(async () => {
      root.render(<CodeBuilder />);
      await flushEffects();
    });

    expect(apiGet).toHaveBeenCalledWith('/code-builder/tasks/persisted-task', { retry: false });
    expect(apiGet).not.toHaveBeenCalledWith('/code-builder/tasks?limit=50', { retry: false });
    expect(JSON.parse(localStorage.getItem('lumina_code_builder_task'))).toEqual(expect.objectContaining({
      task_id: 'persisted-task',
      phase: 'awaiting_approval',
    }));
  });
});