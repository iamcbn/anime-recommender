// frontend/src/types/telemetry.ts

export type TelemetryEndpoint = 'all' | 'recommend' | 'chat' | 'admin_recommend';
export type TelemetrySource = 'all' | 'user' | 'admin_eval';
export type TelemetryStatus = 'all' | 'ok' | 'error';

export interface CandidateScore {
  id: number;
  cross_encoder_score?: number;
  final_rrf_score?: number;
  retrieval_rrf_score?: number;
  [key: string]: unknown;
}

export interface RecommendationLog {
  id: number;
  request_id: string;
  created_at: string;
  endpoint: 'recommend' | 'chat' | 'admin_recommend';
  source: 'user' | 'admin_eval';
  api_key_id: string | null;
  session_id: string | null;
  query: string;
  top_k: number;
  allow_adult: boolean;
  results_count: number;
  status: string;
  status_code: number | null;
  error: string | null;
  total_ms: number | null;
  timings: Record<string, number> | null;
  candidate_scores: CandidateScore[] | null;
  client_metadata: Record<string, unknown> | null;
}

export interface ApiKeyUsageDaily {
  api_key_id: string;
  day: string;
  request_count: number;
}

export interface TelemetryFiltersState {
  endpoint: TelemetryEndpoint;
  source: TelemetrySource;
  status: TelemetryStatus;
  dateRangeDays: number; // 1, 7, 30
  searchQuery: string;
}

export interface PaginationState {
  page: number;
  pageSize: number;
  totalCount: number;
}
