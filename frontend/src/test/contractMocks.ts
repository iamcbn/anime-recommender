// frontend/src/test/contractMocks.ts
/**
 * Canonical typed API response fixtures for contract and anti-drift testing.
 *
 * Adheres strictly to British English documentation standards with zero em-dashes.
 * These fixtures serve as the single source of truth for frontend contract validation.
 */

import type { KeyListResponse, CreateKeyResponse } from '../types/apiKeys';
import type { BudgetMap, DailyUsageItem } from '../types/llmUsage';
import type { RecommendationLog } from '../types/telemetry';
import type { AnimeCandidate } from '../types/chat';

export interface RecommendResponse {
  query: string;
  count: number;
  allowed_adult: boolean;
  results: AnimeCandidate[];
}

export const mockRecommendResponse: RecommendResponse = {
  "query": "cyberpunk detective thriller",
  "count": 2,
  "allowed_adult": false,
  "results": [
    {
      "id": 1,
      "title_userPreferred": "Cowboy Bebop",
      "title_english": "Cowboy Bebop",
      "title_romaji": "Cowboy Bebop",
      "coverImage_large": "https://example.com/bebop.jpg",
      "coverImage_medium": "https://example.com/bebop_med.jpg",
      "genres": [
        "Action",
        "Sci-Fi"
      ],
      "studios": [
        "Sunrise"
      ],
      "averageScore": 86,
      "seasonYear": 1998,
      "episodes": 26,
      "format": "TV",
      "synopsis": "A ragtag crew of bounty hunters chases criminals across the solar system.",
      "description": "A ragtag crew of bounty hunters chases criminals across the solar system.",
      "isAdult": false,
      "status": "FINISHED",
      "cross_encoder_score": 5.4321
    },
    {
      "id": 6,
      "title_userPreferred": "Trigun",
      "title_english": "Trigun",
      "title_romaji": "Trigun",
      "coverImage_large": "https://example.com/trigun.jpg",
      "coverImage_medium": "https://example.com/trigun_med.jpg",
      "genres": [
        "Action",
        "Adventure",
        "Sci-Fi"
      ],
      "studios": [
        "Madhouse"
      ],
      "averageScore": 82,
      "seasonYear": 1998,
      "episodes": 26,
      "format": "TV",
      "synopsis": "Vash the Stampede is a wandering gunslinger with a 60 billion double dollar bounty.",
      "description": "Vash the Stampede is a wandering gunslinger with a 60 billion double dollar bounty.",
      "isAdult": false,
      "status": "FINISHED",
      "cross_encoder_score": 4.1025
    }
  ]
};

export const mockDevKeysListResponse: KeyListResponse = {
  "keys": [
    {
      "id": "d9b73b22-83fc-4632-bd8b-70c3be6b6b11",
      "name": "Production Web App",
      "prefix": "ar_live_a1b2c3d4",
      "created_at": "2026-10-01T12:00:00Z",
      "last_used_at": "2026-10-23T18:30:00Z",
      "expires_at": "2026-12-30T12:00:00Z",
      "revoked_at": null
    },
    {
      "id": "e8a64c11-72eb-4521-ac7a-69b2ad5a5a22",
      "name": "Staging Server",
      "prefix": "ar_live_e5f60718",
      "created_at": "2026-10-05T09:15:00Z",
      "last_used_at": "2026-10-20T10:00:00Z",
      "expires_at": "2027-01-03T09:15:00Z",
      "revoked_at": null
    },
    {
      "id": "f7c55d00-61da-3410-9b69-58a1bc494933",
      "name": "Deprecated CLI Client",
      "prefix": "ar_live_9a8b7c6d",
      "created_at": "2026-09-01T08:00:00Z",
      "last_used_at": "2026-09-15T14:20:00Z",
      "expires_at": "2026-11-30T08:00:00Z",
      "revoked_at": "2026-09-20T11:00:00Z"
    }
  ]
};

export const mockDevKeyCreateResponse: CreateKeyResponse = {
  "id": "a1122334-4455-6677-8899-aabbccddeeff",
  "name": "Mobile Client Key",
  "key": "ar_live_12345678_abcdefghijklmnopqrstuvwxyz1234567890ABCDE",
  "prefix": "ar_live_12345678",
  "created_at": "2026-10-24T00:00:00Z"
};

export const mockCurrentBudgetResponse: BudgetMap = {
  "nli": {
    "layer": "nli",
    "current_usage": 12500,
    "limit": 100000,
    "remaining": 87500,
    "soft_limit_hit": false,
    "hard_limit_hit": false,
    "usage_ratio": 0.125
  },
  "retrieval": {
    "layer": "retrieval",
    "current_usage": 168000,
    "limit": 200000,
    "remaining": 32000,
    "soft_limit_hit": true,
    "hard_limit_hit": false,
    "usage_ratio": 0.84
  },
  "presentation": {
    "layer": "presentation",
    "current_usage": 45000,
    "limit": 300000,
    "remaining": 255000,
    "soft_limit_hit": false,
    "hard_limit_hit": false,
    "usage_ratio": 0.15
  }
};

export const mockDailyUsageResponse: DailyUsageItem[] = [
  {
    "date": "2026-10-23",
    "layer": "nli",
    "request_count": 140,
    "prompt_tokens": 18000,
    "completion_tokens": 4500,
    "total_tokens": 22500,
    "estimated_cost_usd": 0.0054,
    "cache_hit_count": 42,
    "fallback_count": 0
  },
  {
    "date": "2026-10-23",
    "layer": "retrieval",
    "request_count": 155,
    "prompt_tokens": 124000,
    "completion_tokens": 31000,
    "total_tokens": 155000,
    "estimated_cost_usd": 0.0372,
    "cache_hit_count": 20,
    "fallback_count": 2
  },
  {
    "date": "2026-10-23",
    "layer": "presentation",
    "request_count": 110,
    "prompt_tokens": 88000,
    "completion_tokens": 22000,
    "total_tokens": 110000,
    "estimated_cost_usd": 0.0264,
    "cache_hit_count": 15,
    "fallback_count": 0
  },
  {
    "date": "2026-10-22",
    "layer": "nli",
    "request_count": 120,
    "prompt_tokens": 15000,
    "completion_tokens": 3800,
    "total_tokens": 18800,
    "estimated_cost_usd": 0.00453,
    "cache_hit_count": 35,
    "fallback_count": 0
  }
];

export const mockTelemetryLogsResponse: RecommendationLog[] = [
  {
    "id": 101,
    "request_id": "b5a2e987-6e47-4952-b8ec-f5a60e1d0f12",
    "created_at": "2026-10-23T18:24:00Z",
    "endpoint": "recommend",
    "source": "user",
    "api_key_id": "d9b73b22-83fc-4632-bd8b-70c3be6b6b11",
    "session_id": null,
    "query": "cyberpunk detective thriller",
    "top_k": 20,
    "allow_adult": false,
    "results_count": 2,
    "status": "ok",
    "status_code": 200,
    "error": null,
    "total_ms": 185.4,
    "timings": {
      "retrieval_ms": 82.1,
      "ranking_ms": 103.3
    },
    "candidate_scores": [
      {
        "id": 1,
        "cross_encoder_score": 5.4321,
        "final_rrf_score": 0.08912,
        "retrieval_rrf_score": 0.04878
      },
      {
        "id": 6,
        "cross_encoder_score": 4.1025,
        "final_rrf_score": 0.07541,
        "retrieval_rrf_score": 0.04123
      }
    ],
    "client_metadata": {
      "client_ip_hash": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
      "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
  },
  {
    "id": 102,
    "request_id": "c6b3f098-7f58-5063-c9fd-06b71f2e1f23",
    "created_at": "2026-10-23T18:25:30Z",
    "endpoint": "admin_recommend",
    "source": "admin_eval",
    "api_key_id": "d9b73b22-83fc-4632-bd8b-70c3be6b6b11",
    "session_id": null,
    "query": "psychological mecha drama",
    "top_k": 10,
    "allow_adult": true,
    "results_count": 1,
    "status": "ok",
    "status_code": 200,
    "error": null,
    "total_ms": 320.8,
    "timings": {
      "retrieval_ms": 140.2,
      "ranking_ms": 180.6
    },
    "candidate_scores": [
      {
        "id": 19,
        "cross_encoder_score": 6.1234,
        "final_rrf_score": 0.09876,
        "retrieval_rrf_score": 0.05432
      }
    ],
    "client_metadata": {
      "client_ip_hash": "8f14e45fceea167a5a36dedd4bea2543",
      "user_agent": "AdminPortal/1.0"
    }
  }
];
