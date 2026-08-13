import fs from 'fs';
import path from 'path';

describe('Executive Advisor workspace', () => {
  test('exposes persistent advisory controls and approval-grade role modes', () => {
    const page = fs.readFileSync(path.join(__dirname, 'ExecutiveAdvisor.jsx'), 'utf8');
    const app = fs.readFileSync(path.join(__dirname, '..', 'App.js'), 'utf8');
    const registry = fs.readFileSync(path.join(__dirname, '..', 'platform', 'moduleRegistry.js'), 'utf8');

    expect(app).toContain('path="advisor" element={<ExecutiveAdvisor />}');
    expect(registry).toContain("name: 'Executive Advisor'");
    expect(page).toContain("['board', 'Board'");
    expect(page).toContain('Deep reasoning');
    expect(page).toContain('Remember this');
    expect(page).toContain('/runtime/advisor/ask');
    expect(page).toContain('/runtime/advisor/memory');
    expect(page).toContain('/runtime/advisor/profile');
  });
});
