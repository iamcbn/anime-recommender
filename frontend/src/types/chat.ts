// frontend/src/types/chat.ts

export interface AnimeCandidate {
  id: number;
  title_userPreferred?: string;
  title_english?: string;
  title_romaji?: string;
  title?: {
    english?: string | null;
    romaji?: string | null;
    userPreferred?: string | null;
  };
  coverImage_large?: string;
  coverImage_medium?: string;
  coverImage?: {
    large?: string | null;
    medium?: string | null;
  };
  genres?: string[];
  studios?: string[];
  averageScore?: number | null;
  meanScore?: number | null;
  seasonYear?: number | null;
  season?: string | null;
  episodes?: number | null;
  format?: string | null;
  synopsis?: string | null;
  description?: string | null;
  isAdult?: boolean;
  status?: string | null;
  cross_encoder_score?: number | null;
}

export interface ChatMetadata {
  query: string;
  effective_query?: string;
  session_id: string;
  user_id?: string;
  count: number;
  candidates: AnimeCandidate[];
  avoid_genres?: string[];
  timings?: Record<string, number>;
}

export interface ChatWarning {
  warning: string;
  detail: string;
  top_score?: number;
  session_id?: string;
}

export interface ChatDone {
  status: string;
  session_id: string;
  user_id?: string;
  tokens_emitted?: number;
  timings?: Record<string, number>;
}

export interface ChatError {
  status?: number;
  code?: string;
  message?: string;
  detail?: string;
  retryAfter?: number;
}

export type ConversationState = 'idle' | 'streaming' | 'completed' | 'error' | 'rate_limited';

export interface UserPreferences {
  seen_ids: number[];
  disliked_genres: string[];
  allow_adult: boolean;
}
