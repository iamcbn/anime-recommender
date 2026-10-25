// frontend/src/lib/chatStream.ts
import { env } from '../config/env';
import { supabase } from './supabase';
import type {
  ChatMetadata,
  ChatWarning,
  ChatDone,
  ChatError,
} from '../types/chat';

export interface StreamChatParams {
  query: string;
  top_k?: number;
  offset?: number;
  allow_adult?: boolean;
  seen_ids?: number[];
  disliked_genres?: string[];
  session_id?: string;
  user_id?: string;
  conversation_history?: Array<{ role: string; content: string }>;
  apiKey?: string;
  signal?: AbortSignal;
  onMetadata?: (data: ChatMetadata) => void;
  onToken?: (token: string, animeId?: number) => void;
  onWarning?: (warning: ChatWarning) => void;
  onDone?: (data: ChatDone) => void;
  onError?: (error: ChatError) => void;
}

export async function streamChat({
  query,
  top_k = 5,
  offset,
  allow_adult = false,
  seen_ids = [],
  disliked_genres = [],
  session_id,
  user_id,
  conversation_history,
  apiKey,
  signal,
  onMetadata,
  onToken,
  onWarning,
  onDone,
  onError,
}: StreamChatParams): Promise<void> {
  const url = `${env.API_BASE_URL}/chat`;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'Accept': 'text/event-stream',
  };

  // Determine effective auth:
  // 1. Explicit parameter apiKey
  // 2. Saved developer key from local storage or env
  // 3. Authenticated Supabase session JWT for registered users (Sprint 9 Task 9.2 user tier)
  let authToken =
    apiKey ||
    localStorage.getItem('ar_live_key') ||
    localStorage.getItem('ar_api_key') ||
    localStorage.getItem('apiKey') ||
    env.API_KEY;

  if (!authToken) {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (session?.access_token) {
        authToken = session.access_token;
      }
    } catch {
      // In anonymous visitor tier, proceed without Authorization header
    }
  }

  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken.trim()}`;
    headers['x-api-key'] = authToken.trim();
  }

  // If user selected disliked genres and they aren't explicitly referenced in the query,
  // append natural guidance so NLI can extract avoid_genres effectively
  let effectiveQuery = query.trim();
  if (disliked_genres.length > 0 && !effectiveQuery.toLowerCase().includes('without') && !effectiveQuery.toLowerCase().includes('no ')) {
    effectiveQuery = `${effectiveQuery} (without ${disliked_genres.join(', ')})`;
  }

  const payload: Record<string, any> = {
    query: effectiveQuery,
    top_k,
    allow_adult,
  };

  if (offset !== undefined) {
    payload.offset = offset;
  }
  if (seen_ids && seen_ids.length > 0) {
    payload.seen_ids = seen_ids;
  }
  if (disliked_genres && disliked_genres.length > 0) {
    payload.disliked_genres = disliked_genres;
  }
  if (session_id) {
    payload.session_id = session_id;
  }
  if (user_id) {
    payload.user_id = user_id;
  }
  if (conversation_history && conversation_history.length > 0) {
    payload.conversation_history = conversation_history;
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      signal,
    });
  } catch (err: any) {
    if (err.name === 'AbortError') {
      return;
    }
    onError?.({
      status: 0,
      code: 'network_error',
      message: err.message || 'Failed to connect to recommendation service.',
    });
    return;
  }

  // Handle Rate Limiting (429)
  if (response.status === 429) {
    const retryHeader = response.headers.get('Retry-After');
    const retrySeconds = retryHeader ? parseInt(retryHeader, 10) : 60;

    let message = 'Rate limit exceeded. Please wait before retrying.';
    try {
      const errBody = await response.json();
      if (errBody?.error?.message) {
        message = errBody.error.message;
      }
    } catch {
      // Fallback to default message
    }

    onError?.({
      status: 429,
      code: 'rate_limit_exceeded',
      message,
      retryAfter: isNaN(retrySeconds) || retrySeconds <= 0 ? 60 : retrySeconds,
    });
    return;
  }

  // Handle Other HTTP Errors
  if (!response.ok) {
    let errorCode = 'api_error';
    let errorMessage = `Service returned HTTP ${response.status}`;

    try {
      const errBody = await response.json();
      if (errBody?.error?.message) {
        errorMessage = errBody.error.message;
        errorCode = errBody.error.code || errorCode;
      } else if (errBody?.detail) {
        errorMessage = typeof errBody.detail === 'string' ? errBody.detail : JSON.stringify(errBody.detail);
      }
    } catch {
      try {
        errorMessage = await response.text();
      } catch {
        // Fallback
      }
    }

    onError?.({
      status: response.status,
      code: errorCode,
      message: errorMessage,
    });
    return;
  }

  if (!response.body) {
    onError?.({
      status: 500,
      code: 'no_response_stream',
      message: 'Server response contained no readable stream.',
    });
    return;
  }

  // SSE Stream Processing
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let hasResolved = false;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Split SSE packets delimited by double newline
      const parts = buffer.split(/\r?\n\r?\n/);
      buffer = parts.pop() || '';

      for (const part of parts) {
        const trimmed = part.trim();
        if (!trimmed) continue;

        let eventType = 'message';
        const dataLines: string[] = [];

        const lines = trimmed.split(/\r?\n/);
        for (const line of lines) {
          if (line.startsWith('event:')) {
            eventType = line.replace(/^event:\s*/, '').trim();
          } else if (line.startsWith('data:')) {
            dataLines.push(line.replace(/^data:\s*/, ''));
          }
        }

        const dataStr = dataLines.join('\n');
        let parsedData: any = null;
        if (dataStr) {
          try {
            parsedData = JSON.parse(dataStr);
          } catch {
            parsedData = dataStr;
          }
        }

        switch (eventType) {
          case 'metadata':
            if (parsedData) {
              onMetadata?.(parsedData as ChatMetadata);
            }
            break;

          case 'token':
            if (parsedData && typeof parsedData === 'object' && 'text' in parsedData) {
              const animeId = typeof parsedData.anime_id === 'number' ? parsedData.anime_id : undefined;
              if (animeId !== undefined) {
                onToken?.(parsedData.text, animeId);
              } else {
                onToken?.(parsedData.text);
              }
            } else if (typeof parsedData === 'string') {
              onToken?.(parsedData);
            }
            break;

          case 'warning':
            if (parsedData) {
              onWarning?.(parsedData as ChatWarning);
            }
            break;

          case 'done':
            hasResolved = true;
            if (parsedData) {
              onDone?.(parsedData as ChatDone);
            } else {
              onDone?.({ status: 'completed', session_id: '', timings: {} });
            }
            break;

          case 'error':
            hasResolved = true;
            onError?.({
              status: 400,
              code: parsedData?.category || 'stream_error',
              message: parsedData?.detail || parsedData?.error || 'Stream encountered an error',
              detail: parsedData?.detail,
            });
            break;

          default:
            break;
        }
      }
    }
  } catch (err: any) {
    hasResolved = true;
    if (err.name === 'AbortError') {
      return;
    }
    onError?.({
      status: 0,
      code: 'stream_interrupted',
      message: err.message || 'Streaming connection interrupted.',
    });
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // Reader may already be closed or released
    }
    if (!hasResolved && !signal?.aborted) {
      onDone?.({ status: 'completed', session_id: '', timings: {} });
    }
  }
}

export interface StreamSinglePitchParams {
  animeId: number;
  query?: string;
  signal?: AbortSignal;
  onToken: (token: string) => void;
  onDone?: (fullPitch: string) => void;
  onError?: (err: any) => void;
}

export async function streamSinglePitch({
  animeId,
  query,
  signal,
  onToken,
  onDone,
  onError,
}: StreamSinglePitchParams): Promise<void> {
  let fullPitch = '';
  try {
    await streamChat({
      query: `pitch:${animeId} ${query || ''}`.trim(),
      signal,
      onToken: (chunk, tokenAnimeId) => {
        if (tokenAnimeId !== undefined && tokenAnimeId !== animeId) {
          return;
        }
        fullPitch += chunk;
        onToken(chunk);
      },
      onDone: () => {
        onDone?.(fullPitch);
      },
      onError: (err) => {
        onError?.(err);
      },
    });
  } catch (err) {
    onError?.(err);
  }
}
