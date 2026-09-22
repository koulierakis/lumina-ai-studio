const fs = require('fs/promises');
const path = require('path');
const { expect } = require('@playwright/test');

const SECRET_VALUES = [
  process.env.LUMINA_E2E_EMAIL,
  process.env.LUMINA_E2E_PASSWORD,
  process.env.LUMINA_E2E_TOKEN,
].filter(Boolean);

function redact(value) {
  let text = String(value || '');
  for (const secret of SECRET_VALUES) {
    text = text.split(secret).join('[REDACTED]');
  }
  return text
    .replace(/Bearer\s+[A-Za-z0-9._~+/=-]+/gi, 'Bearer [REDACTED]')
    .replace(/"access_token"\s*:\s*"[^"]+"/gi, '"access_token":"[REDACTED]"')
    .replace(/"password"\s*:\s*"[^"]+"/gi, '"password":"[REDACTED]"');
}

function safeUrl(url) {
  try {
    const parsed = new URL(url);
    for (const key of [...parsed.searchParams.keys()]) {
      if (/token|password|secret|key|code/i.test(key)) parsed.searchParams.set(key, '[REDACTED]');
    }
    return parsed.toString();
  } catch {
    return redact(url);
  }
}

async function attachDiagnostics(testInfo, diagnostics) {
  const payload = {
    pageErrors: diagnostics.pageErrors.map(redact),
    consoleErrors: diagnostics.consoleErrors.map(redact),
    failedRequests: diagnostics.failedRequests.map((item) => ({
      url: safeUrl(item.url),
      method: item.method,
      failure: redact(item.failure),
    })),
    badResponses: diagnostics.badResponses.map((item) => ({
      url: safeUrl(item.url),
      status: item.status,
      method: item.method,
    })),
    badResponseBodies: (diagnostics.badResponseBodies || []).map((item) => ({
      url: safeUrl(item.url),
      status: item.status,
      method: item.method,
      body: redact(String(item.body || '').slice(0, 3000)),
    })),
  };
  const file = path.join(testInfo.outputDir, 'browser-network-diagnostics.json');
  await fs.mkdir(testInfo.outputDir, { recursive: true });
  await fs.writeFile(file, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  await testInfo.attach('browser-network-diagnostics', {
    path: file,
    contentType: 'application/json',
  });
}

async function signIn(page) {
  const email = process.env.LUMINA_E2E_EMAIL;
  const password = process.env.LUMINA_E2E_PASSWORD;
  if (!email || !password) {
    throw new Error('Set LUMINA_E2E_EMAIL and LUMINA_E2E_PASSWORD for production E2E tests.');
  }

  await page.goto('/login');
  await expect(page.getByTestId('login-form').or(page.getByTestId('logout-btn'))).toBeVisible();
  if (await page.getByTestId('logout-btn').isVisible()) {
    throw new Error('Sign-in E2E requires a fresh context and a frontend started with REACT_APP_LOCAL_DEV_AUTH=false.');
  }
  await expect(page.getByTestId('login-form')).toBeVisible({ timeout: 30000 });
  await page.getByTestId('login-email').fill(email);
  await page.getByTestId('login-password').fill(password);
  const loginResponse = page.waitForResponse((response) => (
    new URL(response.url()).pathname === '/api/auth/login' && response.request().method() === 'POST'
  ));
  await page.getByTestId('login-submit').click();
  expect((await loginResponse).status()).toBe(200);
  await expect(page).toHaveURL(/\/studio\/(generate|dashboard|mind|documents)/, { timeout: 30000 });
  await expect(page.getByTestId('login-form')).toHaveCount(0);
}

async function ensureSignedIn(page) {
  await page.goto('/studio/dashboard');
  // React redirects after document load; the URL alone can still be /dashboard.
  await expect(page.getByTestId('login-form').or(page.getByTestId('logout-btn'))).toBeVisible();
  if (await page.getByTestId('login-form').isVisible()) {
    await signIn(page);
  }
  await page.goto('/studio/dashboard');
  await expect(page).toHaveURL(/\/studio\/dashboard/);
}

async function authenticatedGet(page, endpoint) {
  const apiURL = process.env.LUMINA_E2E_API_URL || `${new URL(page.url()).origin}/api`;
  return page.evaluate(async ({ apiURL, endpoint }) => {
    const token = localStorage.getItem('lumina_token');
    const response = await fetch(`${apiURL}${endpoint}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    return { status: response.status, data: await response.json() };
  }, { apiURL, endpoint });
}

async function openMind(page) {
  await page.goto('/studio/mind');
  await expect(page.getByTestId('lumina-mind-page')).toBeVisible();
  await expect(page.getByRole('heading', { name: /LUMINA Mind/i })).toBeVisible();
}

async function mindComposer(page) {
  return page.locator('main[data-testid="lumina-mind-page"] textarea').first();
}

function mindSendButton(page) {
  return page.locator('main[data-testid="lumina-mind-page"] button:has(svg.lucide-send)').first();
}

module.exports = {
  attachDiagnostics,
  authenticatedGet,
  ensureSignedIn,
  mindComposer,
  mindSendButton,
  openMind,
  signIn,
};
