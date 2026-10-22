// frontend/src/lib/supabase.ts
import { createClient } from '@supabase/supabase-js';
import { env } from '../config/env';
import type { RecommendationLog, ApiKeyUsageDaily } from '../types/telemetry';

export interface Database {
  telemetry: {
    Tables: {
      recommendation_logs: {
        Row: RecommendationLog;
        Insert: Partial<RecommendationLog>;
        Update: Partial<RecommendationLog>;
      };
      api_key_usage_daily: {
        Row: ApiKeyUsageDaily;
        Insert: Partial<ApiKeyUsageDaily>;
        Update: Partial<ApiKeyUsageDaily>;
      };
    };
  };
}

export const supabase = createClient<Database>(env.SUPABASE_URL, env.SUPABASE_ANON_KEY, {
  auth: {
    flowType: 'pkce',
    autoRefreshToken: true,
    persistSession: true,
    detectSessionInUrl: true,
  },
});
