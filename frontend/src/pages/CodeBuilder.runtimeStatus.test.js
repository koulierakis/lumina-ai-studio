import { act } from 'react';
import { createRoot } from 'react-dom/client';
import CodeBuilder from './CodeBuilder';
import { apiGet, apiPost } from '../lib/api';

jest.mock('../lib/api', () => ({ apiGet: jest.fn(), apiPost: jest.fn() }));

describe('Code Builder runtime status controls', () => {
  let container;
  let root;

  beforeEach(() => {
    window.localStorage.clear();
    apiPost.mockReset();
    apiGet.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    global.IS_REACT_ACT_ENVIRONMENT = true;
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    window.localStorage.clear();
    jest.useRealTimers();
  });

  test('manual refresh uses the stored task id instead of the React click event', async () => {
    const task = {
      task_id: 'abc123',
      phase: 'awaiting_approval',
      created_at_epoch: Date.now() / 1000,
      started_at_epoch: Date.now() / 1000,
      events: [],
    };
    window.localStorage.setItem('lumina_code_builder_task_id', task.task_id);
    window.localStorage.setItem('lumina_code_builder_task', JSON.stringify(task));
    apiGet.mockImplementation(async (url) => {
      if (url === '/code-builder/model-status') return { status: 'ready' };
      if (url === '/code-builder/tasks/abc123') return task;
      if (url.startsWith('/code-builder/tasks?')) return { items: [] };
      throw new Error(`Unexpected URL: ${url}`);
    });

    await act(async () => root.render(<CodeBuilder />));
    apiGet.mockClear();

    await act(async () => container.querySelector('[data-testid="code-builder-refresh"]').click());

    expect(apiGet).toHaveBeenCalledWith('/code-builder/tasks/abc123', { retry: false });
    expect(apiGet).not.toHaveBeenCalledWith(expect.stringContaining('[object Object]'), expect.anything());
  });

  test('elapsed time keeps ticking while awaiting approval', async () => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date('2026-08-30T16:00:00Z'));
    const start = Date.now() / 1000;
    const task = {
      task_id: 'timer123',
      phase: 'awaiting_approval',
      created_at_epoch: start,
      started_at_epoch: start,
      events: [],
    };
    window.localStorage.setItem('lumina_code_builder_task_id', task.task_id);
    window.localStorage.setItem('lumina_code_builder_task', JSON.stringify(task));
    apiGet.mockImplementation(async (url) => {
      if (url === '/code-builder/model-status') return { status: 'ready' };
      if (url === '/code-builder/tasks/timer123') return task;
      if (url.startsWith('/code-builder/tasks?')) return { items: [] };
      throw new Error(`Unexpected URL: ${url}`);
    });

    await act(async () => root.render(<CodeBuilder />));
    expect(container.textContent).toContain('0:00');

    await act(async () => {
      jest.advanceTimersByTime(2000);
    });

    expect(container.textContent).toContain('0:02');
  });
});
