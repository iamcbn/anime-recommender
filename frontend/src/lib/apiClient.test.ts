// frontend/src/lib/apiClient.test.ts
/**
 * Unit tests for ApiClientError credential scrubbing, JWT freshness barriers, and developer key APIs.
 *
 * Conforms to Sprint 3 Unit Testing standards:
 * - Fast, isolated execution using Vitest without network access.
 * - Strict British English documentation without em-dashes.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { ApiClientError, devKeysApi } from './apiClient';
import { supabase } from './supabase';

describe('ApiClientError credential scrubbing', () => {
  it('redacts live API keys from error messages to prevent credential leakage in UI logs', () => {
    /**
     * Verifies that ApiClientError sanitises ar_live_ API key tokens into [REDACTED_KEY]
     * so that backend validation failures never leak keys into browser consoles or monitoring.
     */
    const rawError = 'Failed to authenticate request with key ar_live_a1b2c3d4_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG.';
    const error = new ApiClientError(401, 'invalid_key', rawError);

    expect(error.message).not.toContain('ar_live_a1b2c3d4');
    expect(error.message).toContain('[REDACTED_KEY]');
    expect(error.status).toBe(401);
    expect(error.code).toBe('invalid_key');
  });

  it('redacts Bearer authorization tokens from error messages', () => {
    /**
     * Verifies that ApiClientError strips raw Bearer JWT strings, ensuring sensitive
     * session tokens are replaced with Bearer [REDACTED].
     */
    const rawError = 'Invalid token signature for header: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0In0.signature';
    const error = new ApiClientError(401, 'invalid_token', rawError);

    expect(error.message).not.toContain('eyJhbGciOi');
    expect(error.message).toContain('Bearer [REDACTED]');
  });
});

describe('JWT freshness check and API Client requests', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('proactively refreshes tokens when issued at timestamp is older than 14 minutes', async () => {
    /**
     * Verifies that getFreshAccessToken detects tokens older than 840 seconds (14 minutes)
     * and refreshes the Supabase session before executing downstream requests.
     */
    const nowSec = Math.floor(Date.now() / 1000);
    const staleIat = nowSec - 900; // 15 minutes old
    const stalePayload = btoa(JSON.stringify({ sub: 'user-1', iat: staleIat }));
    const staleToken = `header.${stalePayload}.signature`;

    const freshPayload = btoa(JSON.stringify({ sub: 'user-1', iat: nowSec }));
    const freshToken = `header.${freshPayload}.new_signature`;

    vi.spyOn(supabase.auth, 'getSession').mockResolvedValue({
      data: {
        session: {
          access_token: staleToken,
        } as any,
      },
      error: null,
    });

    const refreshSpy = vi.spyOn(supabase.auth, 'refreshSession').mockResolvedValue({
      data: {
        session: {
          access_token: freshToken,
        } as any,
      },
      error: null,
    });

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ keys: [] }),
    });
    globalThis.fetch = mockFetch;

    await devKeysApi.listKeys();

    expect(refreshSpy).toHaveBeenCalledTimes(1);
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/dev/keys'),
      expect.objectContaining({
        method: 'GET',
        headers: expect.any(Headers),
      })
    );

    // Verify fresh token was placed in Authorization header
    const headers = mockFetch.mock.calls[0][1].headers as Headers;
    expect(headers.get('Authorization')).toBe(`Bearer ${freshToken}`);
  });

  it('uses existing token without refreshing when token age is within 14 minutes', async () => {
    /**
     * Verifies that getFreshAccessToken skips unnecessary session refreshes
     * when the token is fresh (age <= 14 minutes), preserving network round-trips.
     */
    const nowSec = Math.floor(Date.now() / 1000);
    const recentIat = nowSec - 300; // 5 minutes old
    const payload = btoa(JSON.stringify({ sub: 'user-1', iat: recentIat }));
    const validToken = `header.${payload}.signature`;

    vi.spyOn(supabase.auth, 'getSession').mockResolvedValue({
      data: {
        session: {
          access_token: validToken,
        } as any,
      },
      error: null,
    });

    const refreshSpy = vi.spyOn(supabase.auth, 'refreshSession');

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ keys: [] }),
    });
    globalThis.fetch = mockFetch;

    await devKeysApi.listKeys();

    expect(refreshSpy).not.toHaveBeenCalled();
    const headers = mockFetch.mock.calls[0][1].headers as Headers;
    expect(headers.get('Authorization')).toBe(`Bearer ${validToken}`);
  });

  it('throws an unauthorized ApiClientError when no active session exists', async () => {
    /**
     * Verifies that requests fail fast with 401 unauthorized when the user is not authenticated.
     */
    vi.spyOn(supabase.auth, 'getSession').mockResolvedValue({
      data: { session: null },
      error: null,
    });

    await expect(devKeysApi.listKeys()).rejects.toThrowError(ApiClientError);
    await expect(devKeysApi.listKeys()).rejects.toMatchObject({
      status: 401,
      code: 'unauthorized',
    });
  });

  it('executes createKey and revokeKey with expected HTTP methods and payloads', async () => {
    /**
     * Verifies that devKeysApi endpoints send properly formatted requests for key creation and revocation.
     */
    const nowSec = Math.floor(Date.now() / 1000);
    const payload = btoa(JSON.stringify({ sub: 'user-1', iat: nowSec }));
    const validToken = `header.${payload}.signature`;

    vi.spyOn(supabase.auth, 'getSession').mockResolvedValue({
      data: {
        session: { access_token: validToken } as any,
      },
      error: null,
    });

    const mockFetch = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ id: 'new-key-1', raw_key: 'ar_live_...' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 204,
      });
    globalThis.fetch = mockFetch;

    // Create key
    await devKeysApi.createKey('production-agent');
    expect(mockFetch).toHaveBeenNthCalledWith(
      1,
      expect.stringContaining('/dev/keys'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ name: 'production-agent' }),
      })
    );

    // Revoke key
    await devKeysApi.revokeKey('target-key-id');
    expect(mockFetch).toHaveBeenNthCalledWith(
      2,
      expect.stringContaining('/dev/keys/target-key-id'),
      expect.objectContaining({
        method: 'DELETE',
      })
    );
  });
});
