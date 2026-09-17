const { test, expect } = require('@playwright/test');
const {
  attachDiagnostics,
  ensureSignedIn,
  mindComposer,
  mindSendButton,
  openMind,
  signIn,
} = require('./helpers/lumina');

test.describe('Lumina Render production smoke', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    const diagnostics = {
      pageErrors: [],
      consoleErrors: [],
      failedRequests: [],
      badResponses: [],
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
    page.on('response', (response) => {
      const status = response.status();
      if (status >= 400) {
        diagnostics.badResponses.push({
          url: response.url(),
          status,
          method: response.request().method(),
        });
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
      await attachDiagnostics(testInfo, testInfo.diagnostics);
    }
  });

  test('loads the production application shell', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('body')).toContainText(/Lumina|LUMINA/);
    await expect(page.locator('body')).not.toContainText(/Application error|Service Unavailable|Internal Server Error/i);
  });

  test('signs in with the dedicated production test account', async ({ page }) => {
    await signIn(page);
    await expect(page.locator('body')).toContainText(/Lumina|LUMINA/);
  });

  test('opens Mind after authentication', async ({ page }) => {
    await ensureSignedIn(page);
    await openMind(page);
    await expect(page.getByTestId('advisor-documents-panel')).toBeVisible();
  });

  test('sends a Mind message and receives a persisted assistant response', async ({ page }) => {
    await ensureSignedIn(page);
    await openMind(page);

    const prompt = `Production smoke ${Date.now()}: reply with one short sentence about system readiness.`;
    await (await mindComposer(page)).fill(prompt);
    await mindSendButton(page).click();

    await expect(page.locator('text=LUMINA Mind').last()).toBeVisible({ timeout: 120000 });
    await expect(page.locator('main[data-testid="lumina-mind-page"]')).toContainText(/system|ready|readiness|Lumina|LUMINA/i, { timeout: 120000 });
  });

  test('hands a document creation request from Mind to Documents and creates the document', async ({ page }) => {
    await ensureSignedIn(page);
    await openMind(page);

    const uniqueTitle = `Render E2E Smoke ${Date.now()}`;
    const request = `Create a short document titled ${uniqueTitle} with one paragraph only.`;
    await (await mindComposer(page)).fill(request);
    await mindSendButton(page).click();

    await expect(page).toHaveURL(/\/studio\/documents/, { timeout: 30000 });
    await expect(page.getByText('Lumina Documents')).toBeVisible();
    await expect(page.locator('.doc-title-input')).toHaveValue(new RegExp(uniqueTitle), { timeout: 150000 });
    await expect(page.locator('.doc-save-indicator')).toContainText(/Saved|Ready/i, { timeout: 150000 });
  });
});
