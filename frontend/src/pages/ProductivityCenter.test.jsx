import { act } from 'react';
import { createRoot } from 'react-dom/client';
import ProductivityCenter from './ProductivityCenter';
import { apiGet } from '../lib/api';

jest.mock('../lib/api', () => ({
  apiGet: jest.fn(),
  apiPost: jest.fn(),
  apiPatch: jest.fn(),
  apiDelete: jest.fn(),
}));

describe('ProductivityCenter', () => {
  let container;
  let root;

  beforeEach(() => {
    global.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    jest.restoreAllMocks();
  });

  it('renders the research workspace against the research API', async () => {
    apiGet.mockResolvedValue([]);
    await act(async () => { root.render(<ProductivityCenter mode="research" />); });
    expect(container.querySelector('[data-testid="productivity-center"]')).not.toBeNull();
    expect(container.textContent).toContain('Research Workspace');
    expect(apiGet).toHaveBeenCalledWith('/research/items');
  });

  it('renders the automation center against the automations API', async () => {
    apiGet.mockResolvedValue([]);
    await act(async () => { root.render(<ProductivityCenter mode="automations" />); });
    expect(container.querySelector('[data-testid="productivity-center"]')).not.toBeNull();
    expect(container.textContent).toContain('Automation Center');
    expect(apiGet).toHaveBeenCalledWith('/automations/tasks');
  });

  it('falls back to the finance view without a mode', async () => {
    apiGet.mockResolvedValue([]);
    await act(async () => { root.render(<ProductivityCenter />); });
    expect(container.querySelector('[data-testid="productivity-center"]')).not.toBeNull();
    expect(apiGet).toHaveBeenCalledWith('/finance/entries');
  });
});
