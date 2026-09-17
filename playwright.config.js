const { defineConfig, devices } = require('@playwright/test');

const baseURL = process.env.LUMINA_E2E_BASE_URL || 'https://lumina-ai-studio.onrender.com';

module.exports = defineConfig({
  testDir: './e2e',
  timeout: 180000,
  expect: { timeout: 30000 },
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { outputFolder: 'test_reports/playwright-html', open: 'never' }]],
  outputDir: 'test_reports/playwright-artifacts',
  use: {
    baseURL,
    actionTimeout: 30000,
    navigationTimeout: 60000,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
