import { activeJobs, buildMessages, formatRelativeTime, suggestedActions } from './model';

describe('control center model', () => {
  it('keeps only actionable jobs and creates relevant next actions', () => {
    const jobs = [{ status: 'queued' }, { status: 'completed' }, { status: 'processing' }];
    expect(activeJobs(jobs)).toHaveLength(2);
    expect(suggestedActions({ jobs, gallery: [], projects: [] }).map((item) => item.title)).toContain('Create your first image');
  });

  it('builds system messages from real workspace state', () => {
    const messages = buildMessages({
      jobs: [{ status: 'processing' }],
      providers: [{ configured: true, healthy: true }],
      gallery: [],
      system: { system_ready: true, overall_readiness: 'ready' },
    });
    expect(messages.map((item) => item.title)).toEqual(
      expect.arrayContaining([
        'System ready — backend, frontend and local AI are online',
        '1 job in progress',
        '1 AI provider ready',
      ]),
    );
  });

  it('formats recent timestamps for activity cards', () => {
    expect(formatRelativeTime('2026-07-24T10:00:00.000Z', Date.parse('2026-07-24T10:05:00.000Z'))).toBe('5m ago');
  });
});
