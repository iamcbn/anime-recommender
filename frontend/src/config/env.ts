// frontend/src/config/env.ts
/**
 * Strict Environment Variable Validation & Configuration.
 * Enforces that only public client-safe Vite variables are loaded.
 * Runtime assertion actively blocks build/execution if backend secrets are accidentally exposed.
 */

const FORBIDDEN_SECRET_KEYS = [
  'SUPABASE_SERVICE_ROLE_KEY',
  'SERVICE_ROLE_KEY',
  'KEY_PEPPER',
  'ADMIN_API_KEY',
  'DATABASE_URL',
  'DB_PASSWORD',
  'JWT_SECRET',
  'OPENAI_API_KEY',
  'OPENAI_SECRET',
  'OPENAI_KEY',
];

// Security audit of import.meta.env
for (const key of Object.keys(import.meta.env || {})) {
  for (const forbidden of FORBIDDEN_SECRET_KEYS) {
    if (key.toUpperCase().includes(forbidden)) {
      throw new Error(
        `[SECURITY VIOLATION] Critical secret "${key}" detected in frontend client environment. ` +
        `Backend secrets must NEVER be prefixed with VITE_ or imported into the browser bundle.`
      );
    }
  }
}

export interface AppEnv {
  SUPABASE_URL: string;
  SUPABASE_ANON_KEY: string;
  API_BASE_URL: string;
  API_KEY?: string;
}

export const env: AppEnv = {
  SUPABASE_URL: import.meta.env.VITE_SUPABASE_URL || 'https://placeholder-project.supabase.co',
  SUPABASE_ANON_KEY: import.meta.env.VITE_SUPABASE_ANON_KEY || 'placeholder-anon-key',
  API_BASE_URL: (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8001').replace(/\/+$/, ''),
  API_KEY: import.meta.env.VITE_API_KEY as string | undefined,
};
