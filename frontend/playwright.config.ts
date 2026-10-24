import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright E2E configuration for anime recommender portal.
 * Validates critical user journeys on headless Chromium against the Vite dev server.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 30000,
  fullyParallel: false,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    headless: true,
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
      },
    },
  ],
  webServer: {
    command: 'npx vite --port 5173',
    port: 5173,
    reuseExistingServer: false,
    timeout: 30000,
  },
});
