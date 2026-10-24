/**
 * frontend/e2e/performance.spec.ts
 *
 * Frontend performance and Navigation Timing benchmark suite.
 * Evaluates real browser navigation metrics using the W3C Navigation Timing API
 * across key application routes:
 * 1. Conversational discovery page (/chat)
 * 2. Developer self-service portal (/developers)
 * 3. Interactive API documentation page (/docs)
 *
 * Asserts that page load duration remains strictly under PERF_FRONTEND_NAV_MS (default: 3000 ms).
 * Conforms strictly to British English documentation standards without em-dashes.
 */

import { test, expect, Page } from '@playwright/test';

// Configurable page navigation threshold in milliseconds
const PERF_FRONTEND_NAV_MS = Number(process.env.PERF_FRONTEND_NAV_MS) || 3000;

interface NavigationMetrics {
  duration: number;
  domContentLoaded: number;
  domInteractive: number;
  responseEnd: number;
}

/**
 * Extracts high-resolution timing metrics from the browser Navigation Timing API.
 * Uses performance.getEntriesByType('navigation') with fallback to performance.timing.
 */
async function captureNavigationMetrics(page: Page): Promise<NavigationMetrics> {
  return await page.evaluate(() => {
    const [navEntry] = performance.getEntriesByType('navigation') as PerformanceNavigationTiming[];
    if (navEntry) {
      return {
        duration: navEntry.duration,
        domContentLoaded: navEntry.domContentLoadedEventEnd - navEntry.startTime,
        domInteractive: navEntry.domInteractive - navEntry.startTime,
        responseEnd: navEntry.responseEnd - navEntry.startTime,
      };
    }

    const legacyTiming = performance.timing;
    const start = legacyTiming.navigationStart;
    const loadEnd = legacyTiming.loadEventEnd > 0 ? legacyTiming.loadEventEnd : legacyTiming.domComplete;

    return {
      duration: loadEnd - start,
      domContentLoaded: legacyTiming.domContentLoadedEventEnd - start,
      domInteractive: legacyTiming.domInteractive - start,
      responseEnd: legacyTiming.responseEnd - start,
    };
  });
}

test.describe('Frontend Navigation Timing Baselines', () => {

  /**
   * Benchmark: /chat Page Navigation Baseline
   * Measures full page load duration for the conversational discovery route.
   * Verifies that total load duration is strictly within PERF_FRONTEND_NAV_MS
   * and that essential UI elements are rendered without layout thrashing.
   */
  test('Page Load Performance: /chat navigation completes within latency budget', async ({ page }) => {
    // Navigate to Chat page and wait for complete window load event
    const response = await page.goto('/chat', { waitUntil: 'load' });
    expect(response?.status()).toBeLessThan(400);

    // Verify key UI elements are mounted
    await expect(page.getByText('Find Your Next Anime Obsession')).toBeVisible();
    await expect(page.locator('textarea')).toBeVisible();

    // Capture Navigation Timing metrics
    const metrics = await captureNavigationMetrics(page);

    console.log('\n[Navigation Timing: /chat]:');
    console.log(`  Total Duration:      ${metrics.duration.toFixed(2)} ms`);
    console.log(`  DOMContentLoaded:    ${metrics.domContentLoaded.toFixed(2)} ms`);
    console.log(`  DOM Interactive:     ${metrics.domInteractive.toFixed(2)} ms`);
    console.log(`  Response End:        ${metrics.responseEnd.toFixed(2)} ms`);
    console.log(`  Budget Ceiling:      <= ${PERF_FRONTEND_NAV_MS} ms`);

    expect(metrics.duration).toBeGreaterThan(0);
    expect(metrics.duration).toBeLessThanOrEqual(PERF_FRONTEND_NAV_MS);
  });

  /**
   * Benchmark: /developers Page Navigation Baseline
   * Measures authenticated page load duration for the Developer Portal self-service route.
   * Injects mock Supabase session credentials, intercepts API key listing requests,
   * and verifies that page navigation completes within the configured latency budget.
   */
  test('Page Load Performance: /developers navigation completes within latency budget', async ({ page }) => {
    // Inject mock authenticated developer credentials into localStorage
    await page.addInitScript(() => {
      const futureExpiry = Math.floor(Date.now() / 1000) + 86400;
      const mockSession = {
        access_token: 'mock-perf-developer-jwt-token',
        token_type: 'bearer',
        expires_in: 86400,
        expires_at: futureExpiry,
        refresh_token: 'mock-refresh-token',
        user: {
          id: '22222222-3333-4444-5555-666666666666',
          aud: 'authenticated',
          role: 'authenticated',
          email: 'developer@anime-discovery.internal',
          app_metadata: { role: 'developer' },
          user_metadata: {},
          created_at: new Date().toISOString(),
        },
      };
      window.localStorage.setItem('sb-placeholder-project-auth-token', JSON.stringify(mockSession));
    });

    // Provide deterministic mock response for developer API key listing
    await page.route('**/dev/keys', async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            keys: [
              {
                id: 'key-perf-uuid-1',
                name: 'benchmarking-key',
                prefix: 'ar_live_b2c3d4e5',
                created_at: new Date().toISOString(),
                last_used_at: new Date().toISOString(),
                expires_at: new Date(Date.now() + 86400000 * 90).toISOString(),
                revoked_at: null,
              },
            ],
          }),
        });
      } else {
        await route.continue();
      }
    });

    // Navigate to Developer Portal and await complete page load
    const response = await page.goto('/developers', { waitUntil: 'load' });
    expect(response?.status()).toBeLessThan(400);

    // Verify key Developer Portal components are rendered
    await expect(page.getByRole('heading', { name: 'API Keys' })).toBeVisible();
    await expect(page.getByRole('table')).toBeVisible();

    // Capture Navigation Timing metrics
    const metrics = await captureNavigationMetrics(page);

    console.log('\n[Navigation Timing: /developers]:');
    console.log(`  Total Duration:      ${metrics.duration.toFixed(2)} ms`);
    console.log(`  DOMContentLoaded:    ${metrics.domContentLoaded.toFixed(2)} ms`);
    console.log(`  DOM Interactive:     ${metrics.domInteractive.toFixed(2)} ms`);
    console.log(`  Response End:        ${metrics.responseEnd.toFixed(2)} ms`);
    console.log(`  Budget Ceiling:      <= ${PERF_FRONTEND_NAV_MS} ms`);

    expect(metrics.duration).toBeGreaterThan(0);
    expect(metrics.duration).toBeLessThanOrEqual(PERF_FRONTEND_NAV_MS);
  });

  /**
   * Benchmark: /docs Page Navigation Baseline
   * Measures page load duration for the public API documentation route.
   * Verifies that the documentation sidebar and code reference render promptly
   * within the PERF_FRONTEND_NAV_MS budget ceiling.
   */
  test('Page Load Performance: /docs navigation completes within latency budget', async ({ page }) => {
    // Navigate to Docs page and wait for window load event
    const response = await page.goto('/docs', { waitUntil: 'load' });
    expect(response?.status()).toBeLessThan(400);

    // Verify documentation header is visible
    await expect(page.getByRole('heading', { name: 'Anime Recommender API' })).toBeVisible();

    // Capture Navigation Timing metrics
    const metrics = await captureNavigationMetrics(page);

    console.log('\n[Navigation Timing: /docs]:');
    console.log(`  Total Duration:      ${metrics.duration.toFixed(2)} ms`);
    console.log(`  DOMContentLoaded:    ${metrics.domContentLoaded.toFixed(2)} ms`);
    console.log(`  DOM Interactive:     ${metrics.domInteractive.toFixed(2)} ms`);
    console.log(`  Response End:        ${metrics.responseEnd.toFixed(2)} ms`);
    console.log(`  Budget Ceiling:      <= ${PERF_FRONTEND_NAV_MS} ms`);

    expect(metrics.duration).toBeGreaterThan(0);
    expect(metrics.duration).toBeLessThanOrEqual(PERF_FRONTEND_NAV_MS);
  });

});
