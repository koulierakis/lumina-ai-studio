import fs from 'fs';
import path from 'path';

describe('Executive Advisor LUMINA Mind orchestration', () => {
  const page = fs.readFileSync(path.join(__dirname, 'ExecutiveAdvisor.jsx'), 'utf8');

  test('asks the advisor with orchestration enabled', () => {
    expect(page).toContain('orchestrate: true');
    expect(page).toContain("'/runtime/advisor/ask'");
  });

  test('renders orchestration results and pending approvals inline', () => {
    expect(page).toContain('mind-orchestration-panel');
    expect(page).toContain('mind-approve-action');
    expect(page).toContain('mind-decline-action');
    expect(page).toContain('needs_approval');
    expect(page).toContain('approval_required');
    expect(page).toContain('onDecide?.');
  });

  test('keeps the studio handoff as navigation fallback on request failure', () => {
    expect(page).toContain('detectStudioIntent(value)');
    expect(page).toContain('navigate(studioHandoff.route, { state: { studioHandoff } })');
    expect(page).toMatch(/if \(studioHandoff\) \{[\s\S]*?navigate\(studioHandoff\.route/);
  });

  test('confirms pending actions through the mind execution endpoint', () => {
    expect(page).toContain("'/runtime/mind/execute'");
    expect(page).toContain('confirmed: true');
    expect(page).toContain("'/runtime/mind/decide'");
  });
});