import { act } from 'react';
import { createRoot } from 'react-dom/client';
import DeveloperCenter from './DeveloperCenter';
import { apiGet } from '../lib/api';

jest.mock('../lib/api', () => ({ apiGet: jest.fn(), apiPost: jest.fn() }));
describe('DeveloperCenter', () => {
  let container;
  let root;

  beforeEach(() => {
    global.IS_REACT_ACT_ENVIRONMENT = true;
    global.fetch = jest.fn(() => new Promise(() => {}));
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    jest.restoreAllMocks();
  });

  it('renders successfully with a partial local overview instead of crashing', async () => {
    apiGet.mockResolvedValue({ repository: { branch: 'main' }, health: { checks: [{ name: 'Backend', status: 'ready' }] }, tasks: [], logs: [], media_jobs: [] });
    await act(async () => { root.render(<DeveloperCenter />); });
    expect(container.querySelector('[data-testid="developer-center-page"]')).not.toBeNull();
    expect(container.textContent).toContain('Repository');
    expect(container.textContent).toContain('main');
  });
});
