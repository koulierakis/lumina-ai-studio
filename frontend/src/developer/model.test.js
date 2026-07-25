import { formatDuration, mergeDeveloperEvent, normalizeDeveloperOverview, pollingFallbackForSse, relativeTime, statusLabel, toSafeErrorMessage } from './model';

describe('Developer Center model', () => {
  it('uses simple user-facing status labels', () => {
    expect(statusLabel('running')).toBe('Working');
    expect(statusLabel('failed')).toBe('Failed');
  });
  it('formats task time for a non-technical user', () => {
    expect(formatDuration(65)).toBe('1m 5s');
    expect(relativeTime('2026-07-24T10:00:00.000Z', Date.parse('2026-07-24T10:02:00.000Z'))).toBe('2m ago');
  });
  it('converts raw objects, Axios responses, and backend detail payloads into strings', () => {
    expect(toSafeErrorMessage({ requestId: 'local' })).toBe('This local panel is temporarily unavailable.');
    expect(toSafeErrorMessage({ response: { data: { detail: { message: 'Database offline' } } } })).toBe('Database offline');
    expect(toSafeErrorMessage({ responseData: { detail: [{ msg: 'Task type is invalid' }] } })).toBe('Task type is invalid');
  });
  it('supplies safe defaults for missing repository and local panel fields', () => {
    const overview = normalizeDeveloperOverview({ health: null, repository: { changed_files: null }, tasks: {}, logs: null, media_jobs: null });
    expect(overview.repository.branch).toBe('Unavailable');
    expect(overview.repository.changed_files).toEqual([]);
    expect(overview.health.checks).toEqual([]);
    expect(overview.tasks).toEqual([]);
  });
  it('keeps valid content usable when one panel has malformed data', () => {
    const overview = normalizeDeveloperOverview({ health: { checks: [{ name: 'Backend', status: 'ready' }] }, repository: { branch: 'main' }, media_jobs: [{ id: 'job-1', title: 'Render', status: 'running' }], logs: 'invalid' });
    expect(overview.health.checks[0].name).toBe('Backend');
    expect(overview.repository.branch).toBe('main');
    expect(overview.media_jobs[0].title).toBe('Render');
    expect(overview.logs).toEqual([]);
  });
  it('uses polling fallback once after SSE failure and accepts a valid snapshot', () => {
    const fallback = pollingFallbackForSse({ detail: { message: 'SSE offline' } });
    expect(fallback).toEqual({ enabled: true, message: 'SSE offline' });
    const updated = mergeDeveloperEvent({ repository: { branch: 'main' } }, 'snapshot', { tasks: [{ id: 'task-1', label: 'Check', status: 'running' }], logs: [] });
    expect(updated.tasks).toHaveLength(1);
    expect(updated.repository.branch).toBe('main');
  });
});
