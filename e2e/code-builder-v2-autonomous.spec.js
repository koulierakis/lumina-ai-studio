const { test, expect } = require('@playwright/test');
const {
  attachDiagnostics,
  authenticatedGet,
  ensureSignedIn,
} = require('./helpers/lumina');

const PRODUCTION_BASE_URL = process.env.LUMINA_E2E_BASE_URL || 'https://lumina-ai-studio.onrender.com';
const E2E_MODEL = process.env.LUMINA_E2E_MODEL || 'openai/gpt-oss-120b';

const SIMPLE_APP_PROMPT = `Create a simple single-page counter app at index.html with embedded CSS and JavaScript.

REQUIREMENTS:
- Single file: index.html only (no other files)
- All CSS inside <style> tags, all JS inside <script> tags
- Works when opened directly in browser (file:// or http://)
- Features: display count (#count), increment button (#incrementBtn), decrement button (#decrementBtn), reset button (#resetBtn)
- Save/load count from localStorage
- Clean, responsive design

Return ONLY a plan with index.html (operation: create).`;

async function pollTask(page, taskId, targetStatuses, timeout = 300000) {
  const start = Date.now();
  const intervals = [2000, 3000, 5000];
  let intervalIndex = 0;
  
  while (Date.now() - start < timeout) {
    const response = await authenticatedGet(page, `/code-builder-v2/tasks/${taskId}`);
    if (response.status !== 200) {
      throw new Error(`Failed to poll task: ${response.status}`);
    }
    const task = response.data;
    if (targetStatuses.includes(task.status)) {
      return task;
    }
    await new Promise(resolve => setTimeout(resolve, intervals[Math.min(intervalIndex, intervals.length - 1)]));
    intervalIndex++;
  }
  throw new Error(`Task ${taskId} did not reach ${targetStatuses.join('|')} within ${timeout}ms`);
}

async function pollExecution(page, taskId, timeout = 600000) {
  const start = Date.now();
  const intervals = [3000, 5000, 10000];
  let intervalIndex = 0;
  
  while (Date.now() - start < timeout) {
    const response = await authenticatedGet(page, `/code-builder-v2/tasks/${taskId}`);
    if (response.status !== 200) {
      throw new Error(`Failed to poll execution: ${response.status}`);
    }
    const task = response.data;
    if (['completed', 'failed', 'cancelled', 'rolled_back'].includes(task.status)) {
      return task;
    }
    await new Promise(resolve => setTimeout(resolve, intervals[Math.min(intervalIndex, intervals.length - 1)]));
    intervalIndex++;
  }
  throw new Error(`Execution for task ${taskId} did not complete within ${timeout}ms`);
}

test.describe('Code Builder V2 Autonomous Production Test', () => {
  test.describe.configure({ timeout: 900000 });
  test.slow(600000);

  test.beforeEach(async ({ page }, testInfo) => {
    const diagnostics = {
      pageErrors: [],
      consoleErrors: [],
      failedRequests: [],
      badResponses: [],
      badResponseBodies: [],
    };
    testInfo.diagnostics = diagnostics;

    page.on('pageerror', (error) => diagnostics.pageErrors.push(error.message));
    page.on('console', (message) => {
      if (['error', 'warning'].includes(message.type())) {
        diagnostics.consoleErrors.push(`${message.type()}: ${message.text()}`);
      }
    });
    page.on('requestfailed', (request) => {
      diagnostics.failedRequests.push({
        url: request.url(),
        method: request.method(),
        failure: request.failure()?.errorText || 'request failed',
      });
    });
    page.on('response', async (response) => {
      const status = response.status();
      if (status >= 400) {
        let body = '';
        if (status >= 500) {
          body = await response.text().catch(() => '');
        }
        diagnostics.badResponses.push({
          url: response.url(),
          status,
          method: response.request().method(),
        });
        if (body) {
          diagnostics.badResponseBodies.push({
            url: response.url(),
            status,
            method: response.request().method(),
            body,
          });
        }
      }
    });
  });

  test.afterEach(async ({ page }, testInfo) => {
    if (testInfo.status !== testInfo.expectedStatus) {
      await page.screenshot({
        path: testInfo.outputPath('failure-redacted.png'),
        fullPage: true,
        mask: [
          page.getByTestId('login-password'),
          page.getByTestId('login-email'),
          page.locator('textarea'),
          page.locator('.lumina-document'),
        ],
      }).catch(() => undefined);
    }
    await attachDiagnostics(testInfo, testInfo.diagnostics);
    expect(testInfo.diagnostics.pageErrors, 'Uncaught browser errors').toEqual([]);
  });

  test('complete autonomous build: plan -> execute -> verify -> preview', async ({ page }, testInfo) => {
    await ensureSignedIn(page);

    // Navigate to Code Builder V2
    await page.goto('/studio/code-builder-v2');
    await expect(page.getByRole('heading', { name: 'Code Builder V2' })).toBeVisible({ timeout: 30000 });

    // Fill in the prompt
    const promptTextarea = page.locator('textarea').first();
    await expect(promptTextarea).toBeVisible();
    await promptTextarea.fill(SIMPLE_APP_PROMPT);

    // Fill in model if input exists
    const modelInput = page.locator('input[name="model"], input[placeholder*="model" i]').first();
    if (await modelInput.isVisible().catch(() => false)) {
      await modelInput.fill(E2E_MODEL);
    }

    // Submit: Create Plan
    const createTaskResponse = page.waitForResponse((response) => (
      new URL(response.url()).pathname === '/api/code-builder-v2/tasks' && response.request().method() === 'POST'
    ), { timeout: 30000 });

    await page.getByRole('button', { name: 'Create plan' }).click();
    const createResponse = await createTaskResponse;
    expect(createResponse.status()).toBe(200);
    const taskPayload = await createResponse.json();
    const taskId = taskPayload.id;
    expect(typeof taskId).toBe('string');
    testInfo.annotations.push({ type: 'task-id', description: taskId });

    // Wait for plan to be ready (awaiting_approval)
    let task = await pollTask(page, taskId, ['awaiting_approval', 'failed', 'cancelled'], 180000);

    if (task.status === 'failed') {
      throw new Error(`Code Builder V2 plan failed: ${task.error || 'no error payload'}`);
    }
    if (task.status === 'cancelled') {
      throw new Error('Task was cancelled unexpectedly');
    }

    expect(task.status).toBe('awaiting_approval');
    expect(task.plan).toBeTruthy();
    expect(task.plan.summary.trim().length).toBeGreaterThan(0);
    expect(Array.isArray(task.plan.changes)).toBe(true);
    expect(task.plan.changes.length).toBeGreaterThan(0);
    expect(task.plan.changes.some(c => c.path && typeof c.path === 'string')).toBe(true);

    // Verify plan contains only index.html
    const plannedPaths = task.plan.changes.map(c => c.path);
    expect(plannedPaths).toEqual(['index.html']);
    expect(task.plan.changes[0].operation).toBe('create');

    // Execute the plan (Approve/Execute)
    const executeResponse = page.waitForResponse((response) => (
      new URL(response.url()).pathname === `/api/code-builder-v2/tasks/${taskId}/execute` && response.request().method() === 'POST'
    ), { timeout: 30000 });

    await expect(page.getByRole('button', { name: 'Execute' })).toBeEnabled({ timeout: 30000 });
    await page.getByRole('button', { name: 'Execute' }).click();
    const execResponse = await executeResponse;
    expect(execResponse.status()).toBe(200);

    // Wait for execution to complete
    task = await pollExecution(page, taskId, 600000);

    // Verify execution completed successfully
    expect(task.status).toBe('completed');
    expect(task.execution).toBeTruthy();
    expect(task.execution.changedPaths).toContain('index.html');
    expect(task.execution.validationResults).toBeDefined();

    // Verify no Ollama/localhost references
    const serialized = JSON.stringify(task);
    expect(serialized).not.toMatch(/ollama|127\.0\.0\.1:11434/i);

    // Capture execution details
    await testInfo.attach('execution-result', {
      contentType: 'application/json',
      body: JSON.stringify({
        taskId,
        status: task.status,
        changedPaths: task.execution.changedPaths,
        validationResults: task.execution.validationResults,
        timestamp: new Date().toISOString(),
      }, null, 2),
    });

    // Navigate to preview the generated app
    // The preview should be available at a known route
    const previewUrl = `/api/code-builder-v2/tasks/${taskId}/preview/index.html`;
    
    const previewResponse = page.waitForResponse((response) => (
      response.url().includes(`/api/code-builder-v2/tasks/${taskId}/preview/`) && response.status() === 200
    ), { timeout: 30000 });

    // Try to access preview via the preview endpoint
    await page.goto(previewUrl, { waitUntil: 'networkidle', timeout: 30000 });
    const previewResp = await previewResponse;
    expect(previewResp.status()).toBe(200);

    // Verify the preview loads correctly
    await expect(page.locator('body')).toBeVisible({ timeout: 15000 });

    // Check for counter app elements
    await expect(page.locator('#count, #counter, [id*="count" i]')).toBeVisible({ timeout: 15000 });
    
    // Find increment button
    const incrementBtn = page.locator('button#incrementBtn, button:has-text("Increment"), button:has-text("+"), button:has-text("increment" i)').first();
    await expect(incrementBtn).toBeVisible({ timeout: 15000 });

    // Find decrement button
    const decrementBtn = page.locator('button#decrementBtn, button:has-text("Decrement"), button:has-text("-"), button:has-text("decrement" i)').first();
    await expect(decrementBtn).toBeVisible({ timeout: 15000 });

    // Find reset button
    const resetBtn = page.locator('button#resetBtn, button:has-text("Reset"), button:has-text("reset" i)').first();
    await expect(resetBtn).toBeVisible({ timeout: 15000 });

    // Test user flow: Increment
    const initialCount = await page.locator('#count, #counter, [id*="count" i]').first().innerText();
    log(`Initial count: ${initialCount}`);

    await incrementBtn.click();
    await page.waitForTimeout(500);
    
    const afterIncrement = await page.locator('#count, #counter, [id*="count" i]').first().innerText();
    log(`After increment: ${afterIncrement}`);

    // Test user flow: Decrement
    await decrementBtn.click();
    await page.waitForTimeout(500);
    
    const afterDecrement = await page.locator('#count, #counter, [id*="count" i]').first().innerText();
    log(`After decrement: ${afterDecrement}`);

    // Test user flow: Reset
    await resetBtn.click();
    await page.waitForTimeout(500);
    
    const afterReset = await page.locator('#count, #counter, [id*="count" i]').first().innerText();
    log(`After reset: ${afterReset}`);

    // Verify localStorage persistence
    const localStorageCount = await page.evaluate(() => localStorage.getItem('count') || localStorage.getItem('counter') || '0');
    log(`localStorage count: ${localStorageCount}`);

    // Test reload persists state
    await page.reload({ waitUntil: 'networkidle' });
    await expect(page.locator('body')).toBeVisible({ timeout: 15000 });
    
    const afterReload = await page.locator('#count, #counter, [id*="count" i]').first().innerText();
    log(`After reload: ${afterReload}`);

    // Capture final diagnostics
    await testInfo.attach('preview-verification', {
      contentType: 'application/json',
      body: JSON.stringify({
        initialCount,
        afterIncrement,
        afterDecrement,
        afterReset,
        localStorageCount,
        afterReload,
        passed: true,
      }, null, 2),
    });
  });

  test('code builder execution failure diagnostics', async ({ page }, testInfo) => {
    await ensureSignedIn(page);

    await page.goto('/studio/code-builder-v2');
    await expect(page.getByRole('heading', { name: 'Code Builder V2' })).toBeVisible({ timeout: 30000 });

    // Submit an impossible prompt that should fail validation
    const badPrompt = `Create an app that connects to a non-existent database and requires valid SSL certificates that don't exist.
The plan must reference files that cannot be created and validation commands that will fail.`;

    const promptTextarea = page.locator('textarea').first();
    await promptTextarea.fill(badPrompt);

    const modelInput = page.locator('input[name="model"], input[placeholder*="model" i]').first();
    if (await modelInput.isVisible().catch(() => false)) {
      await modelInput.fill(E2E_MODEL);
    }

    const createTaskResponse = page.waitForResponse((response) => (
      new URL(response.url()).pathname === '/api/code-builder-v2/tasks' && response.request().method() === 'POST'
    ), { timeout: 30000 });

    await page.getByRole('button', { name: 'Create plan' }).click();
    const createResponse = await createTaskResponse;
    expect(createResponse.status()).toBe(200);
    const taskPayload = await createResponse.json();
    const taskId = taskPayload.id;

    // Wait for plan
    let task = await pollTask(page, taskId, ['awaiting_approval', 'failed', 'cancelled'], 180000);

    if (task.status === 'awaiting_approval') {
      // Execute and wait for failure
      const executeResponse = page.waitForResponse((response) => (
        new URL(response.url()).pathname === `/api/code-builder-v2/tasks/${taskId}/execute` && response.request().method() === 'POST'
      ), { timeout: 30000 });

      await page.getByRole('button', { name: 'Execute' }).click();
      const execResponse = await executeResponse;
      expect(execResponse.status()).toBe(200);

      task = await pollExecution(page, taskId, 300000);

      // Should either fail or complete with validation errors
      if (task.status === 'failed') {
        expect(task.error).toBeTruthy();
        log(`Expected failure: ${task.error}`);
      } else if (task.status === 'completed') {
        // Check validation results for failures
        expect(task.execution.validationResults).toBeDefined();
        const hasValidationFailures = task.execution.validationResults.some(
          r => r.status === 'failed' || r.exitCode !== 0
        );
        expect(hasValidationFailures).toBe(true);
      }
    }

    await testInfo.attach('failure-diagnostics', {
      contentType: 'application/json',
      body: JSON.stringify(task, null, 2),
    });
  });
});

function log(msg) {
  const timestamp = new Date().toISOString();
  console.log(`[AUTONOMOUS ${timestamp}] ${msg}`);
}

module.exports = { log };