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
    expect(page).toContain("const reviewAllowsApproval = review?.status === 'completed'");
    expect(page).toContain("['pass', 'warn'].includes(review?.verdict)");
    expect(page).toContain("const reviewBlocked = review?.verdict === 'block'");
    expect(page).toContain("const canReject = task?.phase === 'awaiting_approval'");
    expect(page).toContain('reviewAllowsApproval;');
    expect(page).toContain('data-testid="code-builder-review-blocked"');
    expect(page).toContain('data-testid="code-builder-review-unavailable"');
    expect(page).toContain('data-testid="code-builder-approve"');
    expect(page).toContain('data-testid="code-builder-reject"');
    expect(page).toContain("disabled={!canReject || busy}");
    expect(page).toContain('data-testid="code-builder-ai-review"');
    expect(page).toContain('data-testid="code-builder-verification"');
    expect(page).toContain('Proposed diff');
    expect(page).toContain('No production writes before explicit approval.');
  });

  test('recovers active work after refresh and prevents accidental duplicate tasks', () => {
    const page = fs.readFileSync(path.join(__dirname, 'CodeBuilder.jsx'), 'utf8');

    expect(page).toContain("const LAST_TASK_STORAGE_KEY = 'lumina_code_builder_last_task_id'");
    expect(page).toContain("apiGet('/code-builder/tasks'");
    expect(page).toContain('ACTIVE_PHASES.has(item?.phase)');
    expect(page).toContain('data-testid="code-builder-recovery-prompt"');
    expect(page).toContain('data-testid="code-builder-recovery-continue"');
    expect(page).toContain('data-testid="code-builder-recovery-background"');
    expect(page).toContain('data-testid="code-builder-recovery-reset"');
    expect(page).toContain('Continue / open task');
    expect(page).toContain('Keep running in background');
    expect(page).toContain('Cancel & reset');
    expect(page).toContain("/cancel`, {");
    expect(page).toContain('disabled={!instruction.trim() || busy || Boolean(recoveryCandidate)}');
    expect(page).toContain('An active Code Builder task already exists.');
  });
});
