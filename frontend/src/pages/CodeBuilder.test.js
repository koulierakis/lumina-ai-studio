import fs from 'fs';
import path from 'path';

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
