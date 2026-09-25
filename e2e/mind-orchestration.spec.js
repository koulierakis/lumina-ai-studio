const { test, expect } = require('@playwright/test');
const {
  attachDiagnostics,
  authenticatedGet,
  authenticatedPost,
  ensureSignedIn,
  mindComposer,
  mindSendButton,
  openMind,
} = require('./helpers/lumina');

async function selectMindProvider(page) {
  const provider = process.env.LUMINA_E2E_MIND_PROVIDER;
  if (provider === 'local') {
    await page.getByRole('button', { name: 'Τοπικό', exact: true }).click();
  } else if (provider === 'sambanova') {
    await page.getByRole('button', { name: 'SambaNova', exact: true }).click();
    await expect.poll(async () => {
      const statusData = await authenticatedGet(page, '/runtime/advisor/status');
      return Boolean(statusData?.data?.sambanova_configured);
    }, { timeout: 30000 }).toBe(true);
  } else if (provider === 'groq') {
    await page.getByRole('button', { name: 'Groq', exact: true }).click();
    await expect.poll(async () => {
      const statusData = await authenticatedGet(page, '/runtime/advisor/status');
      return Boolean(statusData?.data?.groq_configured);
    }, { timeout: 30000 }).toBe(true);
  }
}

function waitForAsk(page, timeout = 180000) {
  return page.waitForResponse((response) => (
    new URL(response.url()).pathname === '/api/runtime/advisor/ask' && response.request().method() === 'POST'
  ), { timeout });
}

test.describe('LUMINA Mind orchestration (real backend)', () => {
  test.describe.configure({ timeout: 300000 });

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
        mask: [page.getByTestId('login-password'), page.getByTestId('login-email'), page.locator('textarea')],
      }).catch(() => undefined);
    }
    await attachDiagnostics(testInfo, testInfo.diagnostics);
    expect(testInfo.diagnostics.pageErrors, 'Uncaught browser errors').toEqual([]);
  });

  test('creates a project through Mind and shows the orchestrated result in-chat', async ({ page }) => {
    await ensureSignedIn(page);
    await openMind(page);
    await selectMindProvider(page);

    const projectName = `Mind Oracle ${Date.now()}`;
    const ask = waitForAsk(page);

    await (await mindComposer(page)).fill(`δημιούργησε ένα έργο με όνομα ${projectName}`);
    await mindSendButton(page).click();

    const askResponse = await ask;
    expect(askResponse.status()).toBe(200);
    const askBody = await askResponse.json();
    expect(askBody.session_id).toBeTruthy();
    expect(askBody.orchestration).toBeTruthy();
    expect(askBody.orchestration.status).toBe('executed');
    expect(askBody.orchestration.capability).toBe('studio');
    expect(askBody.orchestration.action).toBe('create_project');
    expect(askBody.orchestration.result?.id).toBeTruthy();

    const panel = page.getByTestId('mind-orchestration-panel').first();
    await expect(panel).toBeVisible({ timeout: 60000 });
    await expect(panel).toContainText('studio');
    await expect(panel).toContainText('create_project');
    await expect(panel).toContainText(projectName);

    await page.reload();
    await expect(page.getByTestId('lumina-mind-page')).toBeVisible();
    await page.getByRole('button').filter({ hasText: projectName }).first().click();
    const reloadedPanel = page.getByTestId('mind-orchestration-panel').first();
    await expect(reloadedPanel).toBeVisible({ timeout: 60000 });
    await expect(reloadedPanel).toContainText('create_project');
    await expect(reloadedPanel).toContainText(projectName);

    const persisted = await authenticatedGet(page, `/runtime/advisor/sessions/${askBody.session_id}`);
    expect(persisted.status).toBe(200);
    const orchestrated = persisted.data.messages
      .filter((message) => message.role === 'assistant')
      .map((message) => message.orchestration)
      .find((orchestration) => orchestration && orchestration.action === 'create_project');
    expect(orchestrated).toBeTruthy();
    expect(orchestrated.result?.id).toBeTruthy();
  });

  test('lists documents through Mind', async ({ page }) => {
    await ensureSignedIn(page);
    await openMind(page);
    await selectMindProvider(page);

    const ask = waitForAsk(page);

    await (await mindComposer(page)).fill('δείξε μου τα έγγραφά μου');
    await mindSendButton(page).click();

    const askResponse = await ask;
    expect(askResponse.status()).toBe(200);
    const askBody = await askResponse.json();
    expect(askBody.orchestration.status).toBe('executed');
    expect(askBody.orchestration.capability).toBe('documents');
    expect(askBody.orchestration.action).toBe('list');

    const panel = page.getByTestId('mind-orchestration-panel').first();
    await expect(panel).toBeVisible({ timeout: 60000 });
    await expect(panel).toContainText('documents');
    await expect(panel).toContainText('list');
  });

  test('code-builder plan is created and, when reviewable, requires owner approval before execute', async ({ page }) => {
    await ensureSignedIn(page);
    await openMind(page);
    await selectMindProvider(page);

    const ask = waitForAsk(page, 320000);

    await (await mindComposer(page)).fill('φτιάξε κώδικα για να προσθέσεις logging στα services');
    await mindSendButton(page).click();

    const askResponse = await ask;
    expect(askResponse.status()).toBe(200);
    const askBody = await askResponse.json();
    expect(askBody.orchestration.status).toBe('executed');
    expect(askBody.orchestration.capability).toBe('code_builder');
    expect(askBody.orchestration.action).toBe('plan');

    const panel = page.getByTestId('mind-orchestration-panel').first();
    await expect(panel).toBeVisible({ timeout: 150000 });
    await expect(panel).toContainText('code_builder');

    // Real planning is async. When it turned reviewable, the plan's follow-up
    // execute step (repository changes) sits behind an approval gate. Decline
    // through the in-chat button — approving would apply a real repository patch.
    const decline = panel.getByTestId('mind-decline-action');
    const approve = panel.getByTestId('mind-approve-action');
    if (askBody.orchestration.next === 'approval_required' && (await decline.count()) > 0) {
      const decisionResponse = page.waitForResponse((response) => (
        new URL(response.url()).pathname === '/api/runtime/mind/decide' && response.request().method() === 'POST'
      ), { timeout: 120000 });
      await decline.click();
      const decided = await decisionResponse;
      expect(decided.status()).toBe(200);
      expect((await decided.json()).status).toBe('declined');
      await expect(panel).toContainText('Ακυρώθηκε');
      await expect(approve).toHaveCount(0);
      await expect(decline).toHaveCount(0);
    }
  });

  test('an approval-required action executes only after an explicit approve decision', async ({ page }) => {
    await ensureSignedIn(page);
    await openMind(page);
    await selectMindProvider(page);

    const uniqueTag = `Mind Approve ${Date.now()}`;
    const ask = waitForAsk(page);
    await (await mindComposer(page)).fill(`δημιούργησε ένα έγγραφο με τίτλο ${uniqueTag}`);
    await mindSendButton(page).click();

    const createAsk = await ask;
    expect(createAsk.status()).toBe(200);
    const createBody = await createAsk.json();
    expect(createBody.orchestration.status).toBe('executed');
    expect(createBody.orchestration.capability).toBe('documents');
    expect(createBody.orchestration.action).toBe('create');
    const documentId = createBody.orchestration.result?.id;
    expect(documentId).toBeTruthy();

    const seeded = await authenticatedPost(page, '/runtime/mind/execute', {
      capability: 'documents',
      action: 'delete',
      params: { document_id: documentId },
      confirmed: false,
      session_id: createBody.session_id,
    });
    expect(seeded.status).toBe(200);
    expect(seeded.data.status).toBe('needs_approval');

    const decisionAsk = waitForAsk(page);
    await (await mindComposer(page)).fill('ναι');
    await mindSendButton(page).click();

    const approveAskResponse = await decisionAsk;
    expect(approveAskResponse.status()).toBe(200);
    const approveBody = await approveAskResponse.json();
    expect(approveBody.orchestration.status).toBe('executed');
    expect(approveBody.orchestration.capability).toBe('documents');
    expect(approveBody.orchestration.action).toBe('delete');

    const decisionPanel = page.getByTestId('mind-orchestration-panel').last();
    await expect(decisionPanel).toBeVisible({ timeout: 60000 });
    await expect(decisionPanel).toContainText('documents');
    await expect(decisionPanel).toContainText('delete');
    await expect(decisionPanel).toContainText('Εκτελέστηκε');
    await expect(decisionPanel.getByTestId('mind-approve-action')).toHaveCount(0);

    const deleted = await authenticatedGet(page, `/documents/${documentId}`);
    expect(deleted.status).toBe(404);
  });

  test('a pending delete is declined through chat and nothing is executed', async ({ page }) => {
    await ensureSignedIn(page);
    await openMind(page);
    await selectMindProvider(page);

    const uniqueTag = `Mind Decline ${Date.now()}`;
    const ask = waitForAsk(page);
    await (await mindComposer(page)).fill(`δημιούργησε ένα έγγραφο με τίτλο ${uniqueTag}`);
    await mindSendButton(page).click();

    const createAsk = await ask;
    expect(createAsk.status()).toBe(200);
    const createBody = await createAsk.json();
    expect(createBody.orchestration.status).toBe('executed');
    expect(createBody.orchestration.capability).toBe('documents');
    expect(createBody.orchestration.action).toBe('create');
    const documentId = createBody.orchestration.result?.id;
    expect(documentId).toBeTruthy();

    const seeded = await authenticatedPost(page, '/runtime/mind/execute', {
      capability: 'documents',
      action: 'delete',
      params: { document_id: documentId },
      confirmed: false,
      session_id: createBody.session_id,
    });
    expect(seeded.status).toBe(200);
    expect(seeded.data.status).toBe('needs_approval');

    const decisionAsk = waitForAsk(page);
    await (await mindComposer(page)).fill('όχι');
    await mindSendButton(page).click();

    const declineAskResponse = await decisionAsk;
    expect(declineAskResponse.status()).toBe(200);
    const declineBody = await declineAskResponse.json();
    expect(declineBody.orchestration.status).toBe('declined');
    expect(declineBody.orchestration.capability).toBe('documents');
    expect(declineBody.orchestration.action).toBe('delete');

    const decisionPanel = page.getByTestId('mind-orchestration-panel').last();
    await expect(decisionPanel).toBeVisible({ timeout: 60000 });
    await expect(decisionPanel).toContainText('documents');
    await expect(decisionPanel).toContainText('delete');
    await expect(decisionPanel).toContainText('Ακυρώθηκε');
    await expect(decisionPanel.getByTestId('mind-approve-action')).toHaveCount(0);

    const pending = await authenticatedGet(page, `/runtime/mind/pending?session_id=${createBody.session_id}`);
    expect(pending.status).toBe(200);
    expect(pending.data.pending).toBeNull();

    const stillExists = await authenticatedGet(page, `/documents/${documentId}`);
    expect(stillExists.status).toBe(200);
  });
});