// playwright.config.js
const path = require('path');

// Dynamically resolve @playwright/test from frontend/node_modules
const frontendDir = path.resolve(__dirname, 'frontend');

module.exports = {
  testDir: './frontend/e2e',
  timeout: 30000,
  fullyParallel: false,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    headless: true,
  },
  projects: [
    {
      name: 'chromium',
      use: {
        browserName: 'chromium',
      },
    },
  ],
  webServer: {
    command: 'npx vite --port 5173',
    cwd: frontendDir,
    port: 5173,
    reuseExistingServer: false,
    timeout: 30000,
  },
};
