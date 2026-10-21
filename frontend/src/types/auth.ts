// frontend/src/types/auth.ts
import type { User, Session } from '@supabase/supabase-js';

export interface AppMetadata {
  provider?: string;
  providers?: string[];
  role?: 'admin' | 'user' | string;
  [key: string]: unknown;
}

export interface AuthenticatedUser extends User {
  app_metadata: AppMetadata;
}

export interface AuthState {
  user: AuthenticatedUser | null;
  session: Session | null;
  isLoading: boolean;
  isAdmin: boolean;
}

export type AuthMode = 'magic_link' | 'password' | 'signup';
