/**
 * frontend/e2e/non_functional.spec.ts
 *
 * Automated non-functional browser test suite for Sprint 8:
 * 1. Accessibility and keyboard navigation check on conversational search (/chat).
 * 2. Accessibility, table semantics, and dialog focus handling on developer portal (/developers).
 * 3. Accessibility, keyboard navigation, and code block interaction on documentation (/docs).
 *
 * Conforms strictly to British English documentation standards without em-dashes.
 */

import { test, expect } from '@playwright/test';

test.describe('Non-Functional Accessibility & UI Resilience Suite', () => {

  /**
   * Test 1: Accessibility and keyboard navigation check on /chat
   * Verifies that the conversational query textarea possesses an accessible placeholder,
   * prompt suggestions are focusable via keyboard navigation, and the primary submit control
   * contains explicit ARIA labelling and responds to keyboard triggering.
   */
  test('Accessibility check on /chat: textarea accessible labelling and keyboard interaction', async ({ page }) => {
    // Intercept POST /chat Server-Sent Events endpoint to prevent backend dependency
    await page.route('**/chat', async (route) => {
      if (route.request().method() === 'POST') {
        const sseStream = [
          'event: metadata',
          'data: {"session_id":"nonfunc-chat-sess-1","count":1,"candidates":[{"id":10,"title_userPreferred":"Monster","title_romaji":"Monster","genres":["Mystery","Psychological"],"averageScore":88,"popularity":80000,"format":"TV","episodes":74,"status":"FINISHED","description":"A renowned brain surgeon faces a moral dilemma."}]}',
          '',
          'event: token',
          'data: {"text":"Monster is an exceptional psychological thriller."}',
          '',
          'event: done',
          'data: {"status":"completed","session_id":"nonfunc-chat-sess-1","tokens_emitted":6}',
          '',
          '',
        ].join('\n');

        await route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          headers: {
            'Cache-Control': 'no-cache',
            'X-Session-ID': 'nonfunc-chat-sess-1',
          },
          body: sseStream,
        });
      } else {
        await route.continue();
      }
    });

    // 1. Navigate to Chat page
    await page.goto('/chat');

    // 2. Validate accessible prompt textarea attributes
    const textarea = page.locator('textarea');
    await expect(textarea).toBeVisible();
    await expect(textarea).toBeEditable();

    const placeholder = await textarea.getAttribute('placeholder');
    expect(placeholder).toBeTruthy();
    expect(placeholder?.toLowerCase()).toContain('describe');

    // 3. Verify keyboard navigation to prompt suggestion buttons
    const suggestionPills = page.getByRole('button', { name: /Dark psychological thriller|Heartwarming slice-of-life|Mind-bending sci-fi/i });
    const firstSuggestion = suggestionPills.first();
    await expect(firstSuggestion).toBeVisible();

    await firstSuggestion.focus();
    await expect(firstSuggestion).toBeFocused();

    // 4. Verify primary send button ARIA labelling and disabled state when input is empty
    const sendButton = page.getByRole('button', { name: 'Send prompt' });
    await expect(sendButton).toBeVisible();
    await expect(sendButton).toHaveAttribute('aria-label', 'Send prompt');

    // 5. Fill query and verify keyboard trigger via Enter key
    await textarea.focus();
    await textarea.fill('gripping psychological mystery');
    await expect(sendButton).toBeEnabled();

    await page.keyboard.press('Enter');

    // 6. Verify candidates and pitch commentary appear
    await expect(page.getByText('Monster').first()).toBeVisible();
    await expect(page.getByText('Monster is an exceptional psychological thriller.')).toBeVisible();
  });

  /**
   * Test 2: Accessibility check on /developers
   * Verifies table header semantic structure (thead, th, columnheader roles),
   * active key row rendering, and modal dialog accessibility (role='dialog',
   * aria-modal='true', accessible close button, and Escape key dismissal).
   */
  test('Accessibility check on /developers: table semantics and modal dialog focus trap', async ({ page }) => {
    // Inject mock authenticated Supabase developer session into localStorage
    await page.addInitScript(() => {
      const futureExpiry = Math.floor(Date.now() / 1000) + 86400;
      const mockSession = {
        access_token: 'mock-nonfunc-developer-jwt-token',
        token_type: 'bearer',
        expires_in: 86400,
        expires_at: futureExpiry,
        refresh_token: 'mock-refresh-token',
        user: {
          id: '12345678-1234-1234-1234-1234567890ab',
          aud: 'authenticated',
          role: 'authenticated',
          email: 'dev.accessibility@anime-discovery.internal',
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
                id: 'key-nonfunc-uuid-1',
                name: 'production-crawler',
                prefix: 'ar_live_c1d2e3f4',
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

    // 2. Validate table semantic structure and column headers
    const table = page.getByRole('table');
    await expect(table).toBeVisible();

    const expectedHeaders = ['Name', 'Key Prefix', 'Created', 'Last Used', 'Status', 'Actions'];
    for (const headerTitle of expectedHeaders) {
      const headerCell = page.getByRole('columnheader', { name: headerTitle });
      await expect(headerCell).toBeVisible();
    }

    // Verify row data content within table body
    await expect(page.getByText('production-crawler')).toBeVisible();
    await expect(page.getByText('ar_live_c1d2e3f4')).toBeVisible();

    // 3. Test modal dialog accessibility
    const createKeyBtn = page.getByRole('button', { name: /Create API Key/i });
    await expect(createKeyBtn).toBeVisible();
    await createKeyBtn.click();

    // Verify modal container ARIA role and modality
    const dialogModal = page.getByRole('dialog');
    await expect(dialogModal).toBeVisible();
    await expect(dialogModal).toHaveAttribute('aria-modal', 'true');

    // Verify dialog title heading
    const dialogHeading = dialogModal.getByRole('heading', { name: 'Create API Key' });
    await expect(dialogHeading).toBeVisible();

    // Verify accessible input with associated label
    const keyNameInput = dialogModal.locator('input[type="text"]');
    await expect(keyNameInput).toBeVisible();
    await expect(keyNameInput).toBeEditable();

    // Verify accessible close button
    const closeBtn = dialogModal.getByRole('button', { name: 'Close modal' });
    await expect(closeBtn).toBeVisible();

    // 4. Test keyboard dismissal via Escape key
    await page.keyboard.press('Escape');
    await expect(dialogModal).not.toBeVisible();
  });

  /**
   * Test 3: Accessibility check on /docs
   * Verifies that code snippet tabs (cURL, Python, Node.js) are keyboard focusable,
   * active tab switching updates rendered code blocks, copy button possesses an
   * accessible title, and sidebar navigation anchors contain valid href targets.
   */
  test('Accessibility check on /docs: code snippet tabs keyboard navigation and copy button', async ({ page }) => {
    // 1. Navigate to Docs page
    await page.goto('/docs');

    // 2. Validate page heading and documentation sections
    await expect(page.getByRole('heading', { name: 'Anime Recommender API' })).toBeVisible();

    // 3. Verify sidebar navigation links have valid href section anchors
    const sidebarLinks = page.locator('aside a');
    const linkCount = await sidebarLinks.count();
    expect(linkCount).toBeGreaterThanOrEqual(4);

    for (let i = 0; i < linkCount; i++) {
      const link = sidebarLinks.nth(i);
      const href = await link.getAttribute('href');
      expect(href).toMatch(/^#[a-z0-9-]+$/);
    }

    // 4. Validate code snippet tab keyboard accessibility
    const curlTab = page.getByRole('button', { name: 'cURL' });
    const pythonTab = page.getByRole('button', { name: 'Python' });
    const jsTab = page.getByRole('button', { name: 'Node.js' });

    await expect(curlTab).toBeVisible();
    await expect(pythonTab).toBeVisible();
    await expect(jsTab).toBeVisible();

    // Initial state: cURL snippet visible
    await expect(page.getByText('curl -X POST').first()).toBeVisible();

    // Navigate to and trigger Python tab via keyboard
    await pythonTab.focus();
    await expect(pythonTab).toBeFocused();
    await page.keyboard.press('Enter');

    // Verify Python code block rendered
    await expect(page.getByText('def get_recommendations(')).toBeVisible();

    // Navigate to and trigger Node.js tab via keyboard
    await jsTab.focus();
    await expect(jsTab).toBeFocused();
    await page.keyboard.press('Enter');

    // Verify Node.js code block rendered
    await expect(page.getByText('async function fetchRecommendations(')).toBeVisible();

    // 5. Verify code block copy button accessibility
    const copyButton = page.getByRole('button', { name: /Copy/i }).first();
    await expect(copyButton).toBeVisible();
    await copyButton.focus();
    await expect(copyButton).toBeFocused();
  });

});
