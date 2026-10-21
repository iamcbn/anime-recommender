// frontend/src/types/apiKeys.ts

export interface KeyItem {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
}

export interface KeyListResponse {
  keys: KeyItem[];
}

export interface CreateKeyRequest {
  name: string;
}

export interface CreateKeyResponse {
  id: string;
  name: string;
  key: string; // Shown strictly ONCE on creation
  prefix: string;
  created_at: string;
}

export interface ApiErrorDetail {
  code: string;
  message: string;
}

export interface ApiErrorResponse {
  error: ApiErrorDetail;
  detail?: string;
}

export type KeyStatus = 'active' | 'revoked' | 'expired';
