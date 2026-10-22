// frontend/src/lib/apiClient.ts
import { env } from '../config/env';
import { supabase } from './supabase';
import type { KeyListResponse, CreateKeyResponse, ApiErrorResponse } from '../types/apiKeys';

export class ApiClientError extends Error {
  public status: number;
  public code: string;

  constructor(status: number, code: string, message: string) {
    // Sanitize any accidentally leaked keys or Bearer tokens in error messages
    const sanitized = message
      .replace(/ar_live_[a-f0-9]{8}_[A-Za-z0-9_\-]+/gi, '[REDACTED_KEY]')
      .replace(/Bearer\s+[A-Za-z0-9_\-\.]+/gi, 'Bearer [REDACTED]');
    super(sanitized);
    this.name = 'ApiClientError';
    this.status = status;
    this.code = code;
  }
}

/**
 * Ensures session JWT is fresh (< 14 minutes old) to comply with backend
 * get_fresh_current_dev barrier (which enforces iat < 15 minutes).
 */
async function getFreshAccessToken(): Promise<string> {
  const { data: { session }, error } = await supabase.auth.getSession();
  if (error || !session) {
    throw new ApiClientError(401, 'unauthorized', 'Authentication required. Please log in.');
  }

  // Parse JWT iat to verify freshness
  try {
    const payloadBase64 = session.access_token.split('.')[1];
    const decodedJson = JSON.parse(atob(payloadBase64));
    const issuedAt = decodedJson.iat || 0;
    const now = Math.floor(Date.now() / 1000);
    const ageSeconds = now - issuedAt;

    // Proactively refresh if token is older than 14 minutes (840s)
    if (ageSeconds > 840) {
      const { data: refreshData, error: refreshError } = await supabase.auth.refreshSession();
      if (!refreshError && refreshData.session) {
        return refreshData.session.access_token;
      }
    }
  } catch {
    // If parsing fails, fall back to current access token
  }

  return session.access_token;
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = await getFreshAccessToken();
  const url = `${env.API_BASE_URL}${path}`;

  const headers = new Headers(options.headers);
  headers.set('Authorization', `Bearer ${token}`);
  headers.set('Content-Type', 'application/json');
  headers.set('Cache-Control', 'no-store');

  let response = await fetch(url, {
    ...options,
    headers,
  });

  // Transparent retry once if backend returns stale_token or expired_token
  if (response.status === 401) {
    const errorClone = response.clone();
    try {
      const errBody: ApiErrorResponse = await errorClone.json();
      if (errBody.error?.code === 'stale_token' || errBody.error?.code === 'expired_token') {
        const { data: refreshData } = await supabase.auth.refreshSession();
        if (refreshData?.session) {
          headers.set('Authorization', `Bearer ${refreshData.session.access_token}`);
          response = await fetch(url, { ...options, headers });
        }
      }
    } catch {
      // Continue to default error handling
    }
  }

  if (response.status === 204) {
    return {} as T;
  }

  if (!response.ok) {
    let errorCode = 'api_error';
    let errorMessage = `API request failed with status ${response.status}`;

    try {
      const errorData: ApiErrorResponse = await response.json();
      if (errorData.error) {
        errorCode = errorData.error.code || errorCode;
        errorMessage = errorData.error.message || errorMessage;
      } else if (errorData.detail) {
        errorMessage = errorData.detail;
      }
    } catch {
      errorMessage = await response.text();
    }

    throw new ApiClientError(response.status, errorCode, errorMessage);
  }

  return response.json();
}

export const devKeysApi = {
  listKeys: async (): Promise<KeyListResponse> => {
    return request<KeyListResponse>('/dev/keys', { method: 'GET' });
  },

  createKey: async (name: string): Promise<CreateKeyResponse> => {
    return request<CreateKeyResponse>('/dev/keys', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  },

  revokeKey: async (keyId: string): Promise<void> => {
    await request<void>(`/dev/keys/${keyId}`, { method: 'DELETE' });
  },
};
