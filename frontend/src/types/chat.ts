// frontend/src/types/chat.ts

export type StudioItem =
  | string
  | {
      id?: number;
      name?: string;
      isMain?: boolean;
      node?: {
        id?: number;
        name?: string;
        isAnimationStudio?: boolean;
      };
    };

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
  studios?: StudioItem[];
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
  curator_note?: string | null;
  curatorNote?: string | null;
  exclusion_badge?: string | null;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text?: string;
  candidates?: AnimeCandidate[];
  lead_in?: string | null;
  warning?: string | null;
  error?: string | null;
  isStreaming?: boolean;
  timings?: Record<string, number>;
  timestamp: number;
  recommendation_id?: string;
  request_id?: string;
}

export interface ChatMetadata {
  recommendation_id?: string;
  request_id?: string;
  query: string;
  effective_query?: string;
  session_id: string;
  user_id?: string;
  count: number;
  lead_in?: string;
  candidates: AnimeCandidate[];
  avoid_genres?: string[];
  avoid_tropes?: string[];
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

export interface FeedbackEvent {
  recommendation_id: string;
  event_type: 'thumbs_up' | 'thumbs_down' | 'more_like_this' | 'watchlist_add';
  anime_id?: number;
  metadata?: Record<string, unknown>;
}
