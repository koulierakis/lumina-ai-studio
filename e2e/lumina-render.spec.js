const { test, expect } = require('@playwright/test');
const {
  attachDiagnostics,
  authenticatedGet,
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

  test('loads the production application shell', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('body')).toContainText(/Lumina|LUMINA/);
    await expect(page.locator('body')).not.toContainText(/Application error|Service Unavailable|Internal Server Error/i);
  });

  test('signs in with the dedicated production test account', async ({ page }) => {
    await signIn(page);
    await expect(page.locator('body')).toContainText(/Lumina|LUMINA/);
    await page.reload();
    await expect(page.getByTestId('logout-btn')).toBeVisible();
    const me = await authenticatedGet(page, '/auth/me');
    expect(me.status).toBe(200);
    expect(me.data.email.toLowerCase() === process.env.LUMINA_E2E_EMAIL.trim().toLowerCase()).toBe(true);
    await page.getByTestId('logout-btn').click();
    await expect(page.getByTestId('login-form')).toBeVisible();
    await page.goto('/studio/dashboard');
    await expect(page.getByTestId('login-form')).toBeVisible();
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
if (process.env.LUMINA_E2E_MIND_PROVIDER === 'local') {
      await page.getByRole('button', { name: 'Τοπικό', exact: true }).click();
    }
    if (process.env.LUMINA_E2E_MIND_PROVIDER === 'sambanova') {
      await page.getByRole('button', { name: 'SambaNova', exact: true }).click();
    }
    if (process.env.LUMINA_E2E_MIND_PROVIDER === 'groq') {
      await page.getByRole('button', { name: 'Groq', exact: true }).click();
      // Wait until the loaded advisor status proves Groq is configured, so the
      // frontend never blocks the send on a not-yet-loaded status payload.
      await expect.poll(async () => page.evaluate(async ({ apiURL }) => {
        const token = localStorage.getItem('lumina_token');
        const response = await fetch(`${apiURL}/runtime/advisor/status`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        const payload = await response.json();
        return Boolean(payload?.groq_configured);
      }, { apiURL: process.env.LUMINA_E2E_API_URL || `${new URL(page.url()).origin}/api` }), {
        timeout: 30000,
      }).toBe(true);
    }
    await (await mindComposer(page)).fill(prompt);
    const responsePromise = page.waitForResponse((response) => (
      new URL(response.url()).pathname === '/api/runtime/advisor/ask' && response.request().method() === 'POST'
    ), { timeout: 120000 });
    await mindSendButton(page).click();
    const response = await responsePromise;
    expect(response.status()).toBe(200);
    const answer = await response.json();
    expect(answer.provider_status).toBe('ok');
    expect(answer.error).toBeNull();
    expect(answer.answer.trim().length).toBeGreaterThan(0);
    if (process.env.LUMINA_E2E_MIND_PROVIDER === 'groq') {
      expect(answer.provider).toBe('groq');
      expect(answer.model).toBe(process.env.LUMINA_E2E_MODEL || 'openai/gpt-oss-120b');
    }
    await expect(page.getByTestId('lumina-mind-page')).toContainText(answer.answer);
    await page.reload();
    const persisted = await authenticatedGet(page, `/runtime/advisor/sessions/${answer.session_id}`);
    expect(persisted.status).toBe(200);
    expect(persisted.data.messages.some(message => message.role === 'user' && message.content === prompt)).toBe(true);
    expect(persisted.data.messages.some(message => message.role === 'assistant' && message.content === answer.answer)).toBe(true);
    await page.getByRole('button').filter({ hasText: prompt.slice(0, 72) }).click();
    await expect(page.getByTestId('lumina-mind-page')).toContainText(answer.answer);
  });

  test('hands a document creation request from Mind to Documents and creates the document', async ({ page }) => {
    await ensureSignedIn(page);
    await openMind(page);

    const uniqueTitle = `Render E2E Smoke ${Date.now()}`;
    const request = `Create a short document titled ${uniqueTitle} with one paragraph only.`;
    await (await mindComposer(page)).fill(request);
    const savedPromise = page.waitForResponse((response) => (
      new URL(response.url()).pathname === '/api/documents' && response.request().method() === 'POST'
    ), { timeout: 150000 });
    await mindSendButton(page).click();

    await expect(page).toHaveURL(/\/studio\/documents/, { timeout: 30000 });
    await expect(page.getByText('Lumina Documents')).toBeVisible();
    await expect(page.locator('.doc-title-input')).toHaveValue(new RegExp(uniqueTitle), { timeout: 150000 });
    await expect(page.locator('.doc-save-indicator')).toContainText(/Saved|Ready/i, { timeout: 150000 });
const savedResponse = await savedPromise;
    expect(savedResponse.status()).toBe(200);
    const created = await savedResponse.json();
    expect(created.content_text.trim().length).toBeGreaterThan(0);
    if (process.env.LUMINA_E2E_MIND_PROVIDER === 'groq') {
      const providerStatus = await authenticatedGet(page, '/documents/ai/providers/status');
      expect(providerStatus.status).toBe(200);
      expect(providerStatus.data.default_provider).toBe('groq');
      expect(providerStatus.data.providers.groq.configured).toBe(true);
      expect(providerStatus.data.providers.groq.model).toBe(process.env.LUMINA_E2E_MODEL || 'openai/gpt-oss-120b');
    }
    await expect(page.locator('.lumina-document')).toContainText(created.content_text);
    await page.reload();
    await expect(page.locator('.doc-title-input')).toHaveValue(new RegExp(uniqueTitle));
    await expect(page.locator('.lumina-document')).toContainText(created.content_text);
  });
});
