/**
 * frontend/e2e/critical_flows.spec.ts
 *
 * Fullstack browser automation tests validating critical user journeys:
 * Flow 1: Conversational discovery flow (/chat)
 * Flow 2: Developer Portal self-service flow (/developers)
 * Flow 3: Docs page exploration (/docs)
 *
 * Conforms strictly to British English documentation standards without em-dashes.
 */

import { test, expect } from '@playwright/test';

test.describe('Critical User Journeys', () => {

  /**
   * Flow 1: Conversational discovery flow (/chat)
   * Validates that landing on the Chat page displays the conversational prompt input,
   * submitting an anime description initiates streaming retrieval, and recommended
   * candidate cards with synthesised concierge pitch prose are rendered.
   */
  test('Flow 1: Conversational discovery search renders candidate cards and pitch', async ({ page }) => {
    // Intercept POST /chat Server-Sent Events endpoint to deliver deterministic discovery stream
    // Ensure GET page navigation to /chat continues to the Vite development server
    await page.route('**/chat', async (route) => {
      if (route.request().method() === 'POST') {
        const sseStream = [
          'event: metadata',
          'data: {"session_id":"playwright-chat-sess-1","count":1,"candidates":[{"id":42,"title_userPreferred":"Steins;Gate","title_romaji":"Steins;Gate","title_english":"Steins;Gate","genres":["Sci-Fi","Suspense"],"averageScore":91,"popularity":120000,"format":"TV","episodes":24,"status":"FINISHED","description":"Eccentric scientist Rintaro Okabe accidentally invents time travel."}]}',
          '',
          'event: token',
          'data: {"text":"Steins;Gate is a thrilling time-travel masterpiece with phenomenal character depth."}',
          '',
          'event: done',
          'data: {"status":"completed","session_id":"playwright-chat-sess-1","tokens_emitted":10}',
          '',
          '',
        ].join('\n');

        await route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          headers: {
            'Cache-Control': 'no-cache',
            'X-Session-ID': 'playwright-chat-sess-1',
          },
          body: sseStream,
        });
      } else {
        await route.continue();
      }
    });

    // 1. Navigate to Chat page
    await page.goto('/chat');

    // 2. Validate welcome guide and prompt input visibility
    await expect(page.getByText('Find Your Next Anime Obsession')).toBeVisible();

    const promptInput = page.locator('textarea');
    await expect(promptInput).toBeVisible();
    await expect(promptInput).toHaveAttribute('placeholder', /Describe what you feel like watching/i);

    // 3. Enter a conversational prompt and submit search
    await promptInput.fill('mind-bending time travel thriller');
    const sendButton = page.getByRole('button', { name: /Send prompt/i });
    await expect(sendButton).toBeEnabled();
    await sendButton.click();

    // 4. Validate that streaming commentary and candidate card are rendered
    await expect(page.getByText('Recommended Candidates (1)')).toBeVisible();
    await expect(page.getByText('Steins;Gate').first()).toBeVisible();
    await expect(page.getByText('Sci-Fi').first()).toBeVisible();
    await expect(page.getByText('Steins;Gate is a thrilling time-travel masterpiece')).toBeVisible();
  });

  /**
   * Flow 2: Developer Portal self-service flow (/developers)
   * Validates that authenticated developers can access the portal, view their key quota banner
   * showing active allocation (e.g. 1 / 5 keys), and inspect the active API keys table.
   */
  test('Flow 2: Developer Portal displays quota banner and key management table', async ({ page }) => {
    // Inject mock authenticated Supabase session with future expires_at into localStorage
    await page.addInitScript(() => {
      const futureExpiry = Math.floor(Date.now() / 1000) + 86400;
      const mockSession = {
        access_token: 'mock-playwright-developer-jwt-token',
        token_type: 'bearer',
        expires_in: 86400,
        expires_at: futureExpiry,
        refresh_token: 'mock-refresh-token',
        user: {
          id: '11111111-2222-3333-4444-555555555555',
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

    // Mock /dev/keys response to deliver deterministic API key list
    await page.route('**/dev/keys', async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            keys: [
              {
                id: 'key-playwright-uuid-1',
                name: 'staging-indexer',
                prefix: 'ar_live_a1b2c3d4',
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

    // 1. Navigate to Developer Portal
    await page.goto('/developers');

    // 2. Validate header and Create API Key button
    await expect(page.getByRole('heading', { name: 'API Keys' })).toBeVisible();
    await expect(page.getByRole('button', { name: /Create API Key/i })).toBeVisible();

    // 3. Validate Key Quota Banner
    await expect(page.getByText('Active keys: 1 / 5')).toBeVisible();
    await expect(page.getByText('Rate limit: 20 req/min')).toBeVisible();

    // 4. Validate Key Management Table renders columns and active key row
    await expect(page.getByRole('table')).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Name' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Key Prefix' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Status' })).toBeVisible();
    await expect(page.getByText('staging-indexer')).toBeVisible();
    await expect(page.getByText('ar_live_a1b2c3d4')).toBeVisible();
    await expect(page.getByText('Active').first()).toBeVisible();
  });

  /**
   * Flow 3: Docs page exploration (/docs)
   * Validates API reference sidebar navigation between documentation anchors
   * and interactive switching across code snippet language tabs (cURL, Python, Node.js).
   */
  test('Flow 3: Docs page navigation and code snippet language switching', async ({ page }) => {
    // 1. Navigate to public Docs page
    await page.goto('/docs');
    await expect(page.getByRole('heading', { name: 'Anime Recommender API' })).toBeVisible();

    // 2. Validate API Reference sidebar links
    const sidebar = page.locator('aside');
    await expect(sidebar.getByRole('link', { name: 'Authentication' })).toBeVisible();
    await expect(sidebar.getByRole('link', { name: 'POST /recommend' })).toBeVisible();
    await expect(sidebar.getByRole('link', { name: 'Code Examples' })).toBeVisible();
    await expect(sidebar.getByRole('link', { name: 'Errors' })).toBeVisible();
    await expect(sidebar.getByRole('link', { name: 'Key Rotation' })).toBeVisible();

    // 3. Click POST /recommend link in sidebar and verify destination header is present
    await sidebar.getByRole('link', { name: 'POST /recommend' }).click();
    await expect(page.locator('#post-recommend')).toBeVisible();

    // 4. Validate interactive code sample language tabs
    const curlTab = page.getByRole('button', { name: 'cURL' });
    const pythonTab = page.getByRole('button', { name: 'Python' });
    const nodeTab = page.getByRole('button', { name: 'Node.js' });

    await expect(curlTab).toBeVisible();
    await expect(pythonTab).toBeVisible();
    await expect(nodeTab).toBeVisible();

    // Default tab is cURL
    await expect(page.getByText('curl -X POST')).toBeVisible();

    // Switch to Python tab
    await pythonTab.click();
    await expect(page.getByText('import requests')).toBeVisible();
    await expect(page.getByText('def get_recommendations')).toBeVisible();

    // Switch to Node.js tab
    await nodeTab.click();
    await expect(page.getByText('fetchRecommendations')).toBeVisible();
  });

});
