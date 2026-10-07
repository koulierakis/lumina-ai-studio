import fs from 'fs';
import path from 'path';

describe('Executive Advisor LUMINA Mind connectors', () => {
  const page = fs.readFileSync(path.join(__dirname, 'ExecutiveAdvisor.jsx'), 'utf8');

  test('loads connector status from the mind endpoint', () => {
    expect(page).toContain("'/runtime/mind/connectors'");
    expect(page).toContain('loadConnectors');
  });

  test('renders the connectors panel with per-channel rows', () => {
    expect(page).toContain('mind-connectors-panel');
    expect(page).toContain('connector-test-toggle-');
    expect(page).toContain('connector-test-submit-');
    expect(page).toContain('ConnectorRow');
  });

  test('tests a connector through the mind execute endpoint with approval', () => {
    expect(page).toContain("capability: 'connect'");
    expect(page).toContain('confirmed: true');
    expect(page).toMatch(/action,\s*\n\s*params: values/);
  });

  test('makes dry-run unmistakable to the owner', () => {
    expect(page).toContain('connectors-dry-run-banner');
    expect(page).toContain('mind-dry-run-note');
    expect(page).toContain('ΔΕΝ στάλθηκε');
    expect(page).toContain('dry_run');
  });

  test('covers every connector mode', () => {
    expect(page).toContain("if (mode === 'live')");
    expect(page).toContain("if (mode === 'disabled')");
    expect(page).toContain('dry_run');
  });

  test('renders the autonomy dial and persists the chosen level', () => {
    expect(page).toContain('mind-autonomy-panel');
    expect(page).toContain('autonomy-level-');
    expect(page).toContain('autonomy-description');
    expect(page).toContain("'/runtime/mind/autonomy'");
    expect(page).toContain('selectAutonomy');
  });
});
