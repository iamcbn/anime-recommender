// frontend/src/config/env.test.ts
/**
 * Unit tests for client-safe environment variable loading and secret leak prevention.
 *
 * Conforms to Sprint 3 Unit Testing standards:
 * - Fast, isolated execution using Vitest without network access.
 * - Strict British English documentation without em-dashes.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

describe('Environment Configuration & Security Audit', () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it('loads default client configuration cleanly when no overrides exist', async () => {
    /**
     * Verifies that the client application defaults to safe local development
     * endpoints when optional environment variables are absent.
     */
    const { env } = await import('./env');

    expect(env).toBeDefined();
    expect(env.SUPABASE_URL).toContain('supabase.co');
    expect(env.SUPABASE_ANON_KEY).toBeDefined();
    expect(env.API_BASE_URL).toBe('http://localhost:8001');
  });

  it('strips trailing slashes from API_BASE_URL to normalise endpoint concatenation', async () => {
    /**
     * Verifies that trailing slashes configured in VITE_API_BASE_URL are stripped
     * to avoid double-slash route errors when making API requests.
     */
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.anime-recommender.com///');

    const { env } = await import('./env');
    expect(env.API_BASE_URL).toBe('https://api.anime-recommender.com');
  });

  it('throws a security violation when backend service role keys appear in import.meta.env', async () => {
    /**
     * Verifies that accidental inclusion of FORBIDDEN SUPABASE_SERVICE_ROLE_KEY triggers
     * immediate runtime refusal, ensuring it is never leaked into browser bundles.
     */
    vi.stubEnv('VITE_SUPABASE_SERVICE_ROLE_KEY', 'secret_service_role_token_12345');

    await expect(async () => {
      await import('./env');
    }).rejects.toThrow(/\[SECURITY VIOLATION\] Critical secret ".*SERVICE_ROLE_KEY.*" detected/);
  });

  it('throws a security violation when HMAC key peppers appear in frontend environment', async () => {
    /**
     * Verifies that FORBIDDEN KEY_PEPPER environment exposure throws a security violation error,
     * ensuring it is never disclosed to clients.
     */
    vi.stubEnv('VITE_KEY_PEPPER', 'top_secret_pepper_value_longer_than_32_bytes');

    await expect(async () => {
      await import('./env');
    }).rejects.toThrow(/\[SECURITY VIOLATION\] Critical secret ".*KEY_PEPPER.*" detected/);
  });

  it('throws a security violation when admin API keys or database URLs appear in environment', async () => {
    /**
     * Verifies that FORBIDDEN administrative breakglass keys and database connection strings
     * trigger security violation errors, ensuring they are never mapped to client environment variables.
     */
    vi.stubEnv('VITE_ADMIN_API_KEY', 'breakglass_admin_secret');

    await expect(async () => {
      await import('./env');
    }).rejects.toThrow(/\[SECURITY VIOLATION\] Critical secret ".*ADMIN_API_KEY.*" detected/);
  });
});
