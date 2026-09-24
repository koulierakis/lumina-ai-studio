const { test, expect } = require('@playwright/test');

const {
  installBrowserDiagnostics,
  authenticatedGet,
  authenticatedFetch,
  fetchHealth,
  openMind,
  mindComposer,
  mindSendButton,
  signIn,
} = require('./helpers/lumina');

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const HAS_CREDS = Boolean(process.env.LUMINA_E2E_EMAIL && process.env.LUMINA_E2E_PASSWORD);

function unique(prefix) {
  return `${prefix}-${Date.now()}`;
}

async function withEvidence(page, testInfo, fn) {
  const diagnostics = await installBrowserDiagnostics(page);
  try {
    await fn();
  } catch (error) {
    await diagnostics.attach(testInfo);
    throw error;
  }
}

async function pollStatus(page, timeoutMs = 60000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const { status, data } = await authenticatedGet(page, '/runtime/advisor/status');
    if (status === 200 && data && data.groq_configured !== undefined) return data;
    await sleep(1500);
  }
  throw new Error('Timed out waiting for /runtime/advisor/status');
}

async function selectProvider(page, statusData) {
  if (statusData.groq_configured) {
    await page.getByRole('button', { name: 'Groq', exact: true }).click();
  } else if (statusData.sambanova_configured) {
    await page.getByRole('button', { name: 'SambaNova', exact: true }).click();
  } else if (statusData.openai_configured) {
    await page.getByRole('button', { name: 'Cloud ανάλυση', exact: true }).click();
  } else if (statusData.local_available) {
    await page.getByRole('button', { name: 'Τοπικό', exact: true }).click();
  } else {
    throw new Error(`No advisor provider available in production. status=${JSON.stringify(statusData)}`);
  }
}

async function pollTask(page, taskId, terminalStatuses, timeoutMs = 180000, stepMs = 2000) {
  const start = Date.now();
  let last = null;
  while (Date.now() - start < timeoutMs) {
    const { status, data } = await authenticatedGet(page, `/code-builder-v2/tasks/${taskId}`);
    if (status !== 200 || !data) {
      last = { httpStatus: status, data };
      await sleep(stepMs);
      continue;
    }
    last = { httpStatus: status, data };
    if (terminalStatuses.includes(data.status)) return data;
    if (data.status === 'executing') return data;
    await sleep(stepMs);
  }
  throw new Error(`Task ${taskId} did not reach a terminal state in time. last=${JSON.stringify(last && {
    httpStatus: last.httpStatus,
    status: last.data && last.data.status,
    error: last.data && last.data.error,
  })}`);
}

test.describe('TEST 1a — unauthenticated production access is rejected', () => {
  test('app shell, /login redirect, 401 on authenticated endpoint without token', async ({ page }, testInfo) => {
    await withEvidence(page, testInfo, async () => {
      await page.goto('/');
      await expect(page.getByTestId('login-form')).toBeVisible({ timeout: 60000 });
      await expect(page).toHaveURL(/\/login/);

      await page.goto('/studio/documents');
      await expect(page.getByTestId('login-form')).toBeVisible({ timeout: 60000 });

      const currentOrigin = new URL(page.url()).origin;
      const response = await page.request.get(`${currentOrigin}/api/auth/me`);
      expect(response.status()).toBe(401);
    });
  });
});

test.describe('TEST 5 — deployed version and component health evidence', () => {
  test('health endpoint reports the deployed commit sha and service status', async ({ page }, testInfo) => {
    await withEvidence(page, testInfo, async () => {
      await page.goto('/');
      const health = await fetchHealth(page);
      expect(health.status).toBe(200);
      expect(health.data).toBeTruthy();
      expect(health.data.status).toBe('ok');
      expect(String(health.data.version || '')).toBeTruthy();
      expect(String(health.data.commit_sha || '')).toBeTruthy();
      await testInfo.attach('deployed-health', {
        contentType: 'application/json',
        body: `${JSON.stringify({ timestamp: new Date().toISOString(), health: health.data }, null, 2)}\n`,
      });
    });
  });
});

test.describe('TEST 1b — authenticated production session', () => {
  test.skip(!HAS_CREDS, 'Requires LUMINA_E2E_EMAIL / LUMINA_E2E_PASSWORD (GitHub Actions secrets).');

  test('real login, token session, /auth/me, dashboard, logout', async ({ page }, testInfo) => {
    await withEvidence(page, testInfo, async () => {
      await signIn(page);

      const token = await page.evaluate(() => localStorage.getItem('lumina_token'));
      expect(token).toBeTruthy();

      const me = await authenticatedGet(page, '/auth/me');
      expect(me.status).toBe(200);
      expect(me.data).toBeTruthy();
      expect(me.data.email).toBe(process.env.LUMINA_E2E_EMAIL);

      await page.goto('/studio/dashboard');
      await expect(page.getByTestId('dashboard-page')).toBeVisible({ timeout: 60000 });
      await expect(page.getByTestId('logout-btn')).toBeVisible();

      await page.getByTestId('logout-btn').click();
      await expect(page).toHaveURL(/\/login/);
      const cleared = await page.evaluate(() => localStorage.getItem('lumina_token'));
      expect(cleared).toBeNull();
    });
  });
});

test.describe('TEST 2 — Mind message persistence across reload', () => {
  test.skip(!HAS_CREDS, 'Requires LUMINA_E2E_EMAIL / LUMINA_E2E_PASSWORD (GitHub Actions secrets).');

  test('send unique message, real assistant answer, server-side persistence, visible after reload', async ({ page }, testInfo) => {
    await withEvidence(page, testInfo, async () => {
      await signIn(page);
      await openMind(page);

      const statusData = await pollStatus(page, 60000);
      await selectProvider(page, statusData);
      await page.locator('main[data-testid="lumina-mind-page"] input[type="checkbox"]').first().uncheck({ force: true });

      const code = unique('GATE-MIND');
      const message = `Reply only once with the token ${code}`;
      await mindComposer(page).fill(message);

      const askResponsePromise = page.waitForResponse((response) => (
        new URL(response.url()).pathname === '/api/runtime/advisor/ask' && response.request().method() === 'POST'
      ));
      await mindSendButton(page).click();
      const askResponse = await askResponsePromise;
      expect(askResponse.status()).toBe(200);

      const askBody = await askResponse.json();
      expect(askBody.session_id).toBeTruthy();
      expect(askBody.provider_status).toBe('ok');
      expect(/currently unavailable/i.test(String(askBody.answer || ''))).toBe(false);
      expect(String(askBody.answer || '').trim().length).toBeGreaterThan(0);

      expect(await page.getByText(code, { exact: false }).count()).toBeGreaterThan(0);

      const session = await authenticatedGet(page, `/runtime/advisor/sessions/${askBody.session_id}`);
      expect(session.status).toBe(200);
      const roles = (session.data.messages || []).map((item) => item.role);
      const contents = (session.data.messages || []).map((item) => String(item.content || ''));
      expect(roles).toContain('user');
      expect(roles).toContain('assistant');
      expect(contents.some((content) => content.includes(code))).toBe(true);
      expect(contents.every((content) => !/currently unavailable/i.test(content))).toBe(true);

      const list = await authenticatedGet(page, '/runtime/advisor/sessions');
      expect(list.status).toBe(200);
      expect(list.data.sessions.some((sessionItem) => String(sessionItem.title || '').includes(code))).toBe(true);

      await page.reload();
      await openMind(page);

      const sessionRow = page.locator('aside').first()
        .locator('div.space-y-1 > div.group')
        .filter({ hasText: code })
        .first();
      await expect(sessionRow).toBeVisible({ timeout: 60000 });
      await sessionRow.locator('button').first().click();

      await expect(page.getByText(code, { exact: false }).first()).toBeVisible({ timeout: 60000 });
      expect(await page.getByText(/currently unavailable/i).count()).toBe(0);
    });
  });
});

test.describe('TEST 3 — Documents create through the real interface', () => {
  test.skip(!HAS_CREDS, 'Requires LUMINA_E2E_EMAIL / LUMINA_E2E_PASSWORD (GitHub Actions secrets).');

  test('create uniquely identified document, persist server-side, render via real preview endpoint', async ({ page }, testInfo) => {
    await withEvidence(page, testInfo, async () => {
      await signIn(page);
      await page.goto('/studio/documents');

      const newButton = page.getByRole('button', { name: 'New', exact: true });
      await expect(newButton).toBeVisible({ timeout: 60000 });

      const createResponsePromise = page.waitForResponse((response) => (
        new URL(response.url()).pathname === '/api/documents' && response.request().method() === 'POST'
      ));
      await newButton.click();
      const createResponse = await createResponsePromise;
      expect(createResponse.status()).toBe(200);
      const created = await createResponse.json();
      expect(created).toBeTruthy();
      expect(String(created.id || '')).toBeTruthy();

      const title = unique('GATE-DOC');
      const titleInput = page.getByLabel('Document title');
      await expect(titleInput).toBeVisible({ timeout: 30000 });
      await titleInput.fill(title);

      const saveResponsePromise = page.waitForResponse((response) => (
        new URL(response.url()).pathname === `/api/documents/${created.id}` && response.request().method() === 'PATCH'
      ));
      await titleInput.blur();
      const saveResponse = await saveResponsePromise;
      expect(saveResponse.status()).toBe(200);

      const list = await authenticatedGet(page, '/documents');
      expect(list.status).toBe(200);
      expect(list.data.some((item) => item.title === title)).toBe(true);

      const single = await authenticatedGet(page, `/documents/${created.id}`);
      expect(single.status).toBe(200);
      expect(single.data.title).toBe(title);

      const preview = await authenticatedFetch(page, `/documents/${created.id}/preview`);
      expect(preview.status).toBe(200);
      expect(preview.contentType).toContain('text/html');
      expect(String(preview.bodyText || '').trim().length).toBeGreaterThan(0);
      expect(String(preview.bodyText || '')).toContain(title);
    });
  });
});

test.describe('TEST 4 — Code Builder V2 safe approval gate', () => {
  test.skip(!HAS_CREDS, 'Requires LUMINA_E2E_EMAIL / LUMINA_E2E_PASSWORD (GitHub Actions secrets).');

  test('planning-only request, real plan + approval controls, safe decline via Cancel, recorded cancelled', async ({ page }, testInfo) => {
    await withEvidence(page, testInfo, async () => {
      await signIn(page);
      await page.goto('/studio/code-builder-v2');

      const createButton = page.getByRole('button', { name: 'Create plan' });
      await expect(createButton).toBeVisible({ timeout: 60000 });

      const code = unique('GATE-CB');
      const prompt = `Plan only and do not apply anything. Create a new scratch file named gate_${code}.txt under the system temp directory containing a single comment line mentioning ${code}.`;
      await page.locator('form textarea').first().fill(prompt);

      const createResponsePromise = page.waitForResponse((response) => (
        new URL(response.url()).pathname === '/api/code-builder-v2/tasks' && response.request().method() === 'POST'
      ));
      await createButton.click();
      const createResponse = await createResponsePromise;
      expect(createResponse.status()).toBe(200);
      const task = await createResponse.json();
      expect(String(task.id || '')).toBeTruthy();

      const terminal = await pollTask(page, task.id, ['awaiting_approval', 'failed', 'cancelled']);

      if (terminal.status === 'awaiting_approval') {
        expect(terminal.plan).toBeTruthy();
        expect(String(terminal.plan.summary || '').trim().length).toBeGreaterThan(0);
        expect(Array.isArray(terminal.plan.changes)).toBe(true);

        await expect(page.getByText(/awaiting approval/i).first()).toBeVisible({ timeout: 60000 });
        await expect(page.getByRole('button', { name: 'Execute' })).toBeEnabled();
        await expect(page.getByRole('button', { name: 'Cancel' })).toBeEnabled();

        const cancelResponsePromise = page.waitForResponse((response) => (
          new URL(response.url()).pathname === `/api/code-builder-v2/tasks/${task.id}/cancel` && response.request().method() === 'POST'
        ));
        await page.getByRole('button', { name: 'Cancel' }).click();
        const cancelResponse = await cancelResponsePromise;
        expect(cancelResponse.status()).toBe(200);

        const cancelled = await pollTask(page, task.id, ['cancelled']);
        expect(cancelled.status).toBe('cancelled');
        expect(cancelled.execution).toBeFalsy();
        await testInfo.attach('code-builder-safe-decline', {
          contentType: 'application/json',
          body: `${JSON.stringify({ timestamp: new Date().toISOString(), taskId: task.id, code, status: cancelled.status }, null, 2)}\n`,
        });
      } else if (terminal.status === 'failed') {
        throw new Error(
          `Code Builder planning failed on production so the approval gate could not be exercised. ` +
          `task=${task.id} status=failed error=${JSON.stringify(terminal.error)}. ` +
          `Expected awaiting_approval with a real plan and Cancel to record declined/cancelled.`,
        );
      } else {
        throw new Error(`Task unexpectedly reached ${terminal.status} before the gate could be exercised.`);
      }
    });
  });
});
