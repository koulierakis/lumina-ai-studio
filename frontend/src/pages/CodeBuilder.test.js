import fs from 'fs';
import path from 'path';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import CodeBuilder from './CodeBuilder';
import { apiGet, apiPost } from '../lib/api';

jest.mock('../lib/api', () => ({ apiGet: jest.fn(), apiPost: jest.fn() }));

class MockSpeechRecognition {
  static instances = [];

  constructor() {
    MockSpeechRecognition.instances.push(this);
  }

  start() {
    this.onstart?.();
  }

  stop() {
    this.onend?.();
  }

  abort() {}
}

describe('Code Builder transactional workspace', () => {
  test('surfaces prepared artifacts and keeps approval behind preparation validation and review', () => {
    const page = fs.readFileSync(path.join(__dirname, 'CodeBuilder.jsx'), 'utf8');
    const app = fs.readFileSync(path.join(__dirname, '..', 'App.js'), 'utf8');
    const registry = fs.readFileSync(path.join(__dirname, '..', 'platform', 'moduleRegistry.js'), 'utf8');

    expect(app).toContain('<Route path="code-builder" element={<CodeBuilder />} />');
    expect(registry).toContain("id: 'code-builder'");
    expect(registry).toContain("route: '/studio/code-builder'");

    expect(page).toContain("task?.phase === 'awaiting_approval'");
    expect(page).toContain('Boolean(preparation?.patch)');
    expect(page).toContain('Boolean(preparation?.patch_validation)');
    expect(page).toContain('Boolean(review)');
    expect(page).toContain('data-testid="code-builder-approve"');
    expect(page).toContain('data-testid="code-builder-reject"');
    expect(page).toContain('data-testid="code-builder-ai-review"');
    expect(page).toContain('data-testid="code-builder-verification"');
    expect(page).toContain("lumina_code_builder_task_id");
    expect(page).toContain("apiGet('/code-builder/tasks?limit=50'");
    expect(page).toContain('data-testid="code-builder-cancel"');
    expect(page).toContain('Proposed diff');
    expect(page).toContain('No production writes before explicit approval.');
  });
});

describe('Code Builder voice composer', () => {
  let container;
  let root;

  beforeEach(() => {
    window.localStorage.clear();
    delete window.SpeechRecognition;
    delete window.webkitSpeechRecognition;
    apiGet.mockResolvedValue({ items: [] });
    apiPost.mockResolvedValue({ task: { task_id: 'task-1', phase: 'queued' } });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    global.IS_REACT_ACT_ENVIRONMENT = true;
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    jest.restoreAllMocks();
    MockSpeechRecognition.instances = [];
  });

  async function renderComposer() {
    await act(async () => root.render(<CodeBuilder />));
  }

  function setTextareaValue(input, value) {
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }

  test('renders a graceful unsupported-browser fallback', async () => {
    await renderComposer();
    await act(async () => container.querySelector('[data-testid="code-builder-voice"]').click());
    expect(container.querySelector('[data-testid="code-builder-voice-status"]').textContent).toContain('not supported');
    expect(apiPost).not.toHaveBeenCalled();
  });

  test('preserves typed text and inserts a Greek transcript without submitting', async () => {
    window.SpeechRecognition = MockSpeechRecognition;
    await renderComposer();
    const input = container.querySelector('[data-testid="code-builder-instruction"]');
    await act(async () => {
      setTextareaValue(input, 'Review the repository');
      container.querySelector('[data-testid="code-builder-voice-language"]').value = 'el-GR';
      container.querySelector('[data-testid="code-builder-voice-language"]').dispatchEvent(new Event('change', { bubbles: true }));
      container.querySelector('[data-testid="code-builder-voice"]').click();
    });

    const recognition = MockSpeechRecognition.instances[0];
    expect(recognition.lang).toBe('el-GR');
    await act(async () => recognition.onresult({ results: [[{ transcript: 'έλεγξε τις δοκιμές' }]] }));
    expect(input.value).toContain('Review the repository');
    expect(input.value).toContain('έλεγξε τις δοκιμές');
    expect(apiPost).not.toHaveBeenCalled();

    await act(async () => container.querySelector('[data-testid="code-builder-voice"]').click());
    expect(container.querySelector('[data-testid="code-builder-voice-status"]').textContent).toContain('Draft');
  });

  test('typed submit remains explicit and functional', async () => {
    await renderComposer();
    const input = container.querySelector('[data-testid="code-builder-instruction"]');
    await act(async () => {
      setTextareaValue(input, 'Run the safe checks');
    });
    await act(async () => container.querySelector('[data-testid="code-builder-create"]').click());
    expect(apiPost).toHaveBeenCalledWith('/code-builder/tasks', expect.objectContaining({ instruction: 'Run the safe checks' }));
  });

  test('handles microphone denial without breaking the composer', async () => {
    window.webkitSpeechRecognition = MockSpeechRecognition;
    await renderComposer();
    await act(async () => container.querySelector('[data-testid="code-builder-voice"]').click());
    const recognition = MockSpeechRecognition.instances[0];
    await act(async () => recognition.onerror({ error: 'not-allowed' }));
    expect(container.querySelector('[data-testid="code-builder-voice"]').textContent).toContain('Microphone denied');
    expect(container.querySelector('[data-testid="code-builder-instruction"]')).not.toBeNull();
  });
});
