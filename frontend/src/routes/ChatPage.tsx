// frontend/src/routes/ChatPage.tsx
import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  Sparkles,
  AlertTriangle,
  Clock,
  AlertCircle,
  Compass,
  Film,
  Zap,
} from 'lucide-react';
import type { AnimeCandidate, ConversationState } from '../types/chat';
import { useUserPreferences } from '../hooks/useUserPreferences';
import { streamChat } from '../lib/chatStream';
import { ChatInput } from '../components/chat/ChatInput';
import { ConciergePitch } from '../components/chat/ConciergePitch';
import { AnimeCard } from '../components/chat/AnimeCard';
import { PreferenceDrawer } from '../components/chat/PreferenceDrawer';
import { ErrorBoundary } from '../components/common/ErrorBoundary';

export const ChatPage: React.FC = () => {
  const [conversationState, setConversationState] = useState<ConversationState>('idle');
  const [query, setQuery] = useState('');
  const [activeQuery, setActiveQuery] = useState('');
  const [candidates, setCandidates] = useState<AnimeCandidate[]>([]);
  const [pitch, setPitch] = useState('');
  const [warning, setWarning] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [rateLimitCountdown, setRateLimitCountdown] = useState<number>(0);
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [highlightedAnimeId, setHighlightedAnimeId] = useState<number | null>(null);
  const [hoveredAnimeId, setHoveredAnimeId] = useState<number | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);
  const highlightTimeoutRef = useRef<NodeJS.Timeout | number | null>(null);
  const { preferences } = useUserPreferences();

  // Rate limit 429 ticking countdown timer
  useEffect(() => {
    if (conversationState !== 'rate_limited' || rateLimitCountdown <= 0) return;

    const timer = setInterval(() => {
      setRateLimitCountdown((prev) => {
        if (prev <= 1) {
          clearInterval(timer);
          setConversationState('idle');
          setErrorMessage(null);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [conversationState, rateLimitCountdown]);

  // Clean up ongoing stream & highlight timer on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      if (highlightTimeoutRef.current) {
        clearTimeout(highlightTimeoutRef.current as any);
      }
    };
  }, []);

  const handleSelectAnime = useCallback((animeId: number) => {
    const el = document.getElementById(`anime-card-${animeId}`);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    setHighlightedAnimeId(animeId);
    if (highlightTimeoutRef.current) {
      clearTimeout(highlightTimeoutRef.current as any);
    }
    highlightTimeoutRef.current = setTimeout(() => {
      setHighlightedAnimeId(null);
      highlightTimeoutRef.current = null;
    }, 2500);
  }, []);

  const handleStop = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setConversationState((prev) => (prev === 'streaming' ? 'completed' : prev));
  }, []);

  const handleSearch = useCallback(
    async (overrideQuery?: string) => {
      const target = (overrideQuery ?? query).trim();
      if (!target) return;
      if (conversationState === 'rate_limited' || rateLimitCountdown > 0) return;

      // Abort any active prior stream
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      const controller = new AbortController();
      abortControllerRef.current = controller;

      setConversationState('streaming');
      setActiveQuery(target);
      setCandidates([]);
      setPitch('');
      setWarning(null);
      setErrorMessage(null);

      await streamChat({
        query: target,
        top_k: 5,
        allow_adult: preferences.allow_adult,
        seen_ids: preferences.seen_ids,
        disliked_genres: preferences.disliked_genres,
        session_id: sessionId,
        signal: controller.signal,
        onMetadata: (metadata) => {
          setCandidates(metadata.candidates || []);
          if (metadata.session_id) {
            setSessionId(metadata.session_id);
          }
        },
        onToken: (chunk) => {
          setPitch((prev) => prev + chunk);
        },
        onWarning: (w) => {
          setWarning(w.detail || w.warning || 'Low retrieval confidence');
        },
        onDone: (done) => {
          setConversationState('completed');
          if (done.session_id) {
            setSessionId(done.session_id);
          }
          abortControllerRef.current = null;
        },
        onError: (err) => {
          abortControllerRef.current = null;
          if (err.status === 429) {
            const seconds = err.retryAfter && err.retryAfter > 0 ? err.retryAfter : 60;
            setConversationState('rate_limited');
            setRateLimitCountdown(seconds);
            setErrorMessage(err.message || 'Rate limit reached. Please wait a moment.');
          } else {
            setConversationState('error');
            setErrorMessage(err.message || err.detail || 'Failed to complete recommendation search.');
          }
        },
      });
    },
    [query, conversationState, rateLimitCountdown, preferences, sessionId]
  );

  const handleMoreLikeThis = useCallback(
    (title: string) => {
      const morePrompt = `More like ${title}`;
      setQuery(morePrompt);
      handleSearch(morePrompt);
    },
    [handleSearch]
  );

  const isStreaming = conversationState === 'streaming';
  const isRateLimited = conversationState === 'rate_limited' || rateLimitCountdown > 0;

  return (
    <div className="min-h-[calc(100vh-3.5rem)] bg-slate-50/50 dark:bg-dark-950 py-8 px-4 sm:px-6 lg:px-8">
      <div className="max-w-4xl mx-auto space-y-6">
        {/* Hero / Header Section */}
        <div className="text-center space-y-2.5">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-brand/10 text-brand dark:bg-brand/20 dark:text-brand-light">
            <Sparkles className="w-3.5 h-3.5" />
            <span>AI Conversational Discovery</span>
          </div>
          <h1 className="text-3xl sm:text-4xl font-extrabold text-slate-900 dark:white tracking-tight">
            Find Your Next Anime Obsession
          </h1>
          <p className="text-sm sm:text-base text-slate-600 dark:text-slate-400 max-w-xl mx-auto leading-relaxed">
            Describe a mood, character archetype, or complex trope. Our neural concierge matches and pitches personalized titles in real time.
          </p>
        </div>

        {/* Conversational Prompt Bar */}
        <div className="sticky top-16 z-20 bg-slate-50/90 dark:bg-dark-950/90 backdrop-blur-md pb-2 pt-1">
          <ChatInput
            value={query}
            onChange={setQuery}
            onSubmit={(val) => handleSearch(val)}
            onStop={handleStop}
            isStreaming={isStreaming}
            disabled={isRateLimited}
            placeholder={
              isRateLimited
                ? `Search paused (${rateLimitCountdown}s remaining)...`
                : 'Describe what you feel like watching...'
            }
          />
        </div>

        {/* Collapsible Tuning / Preferences Drawer */}
        <PreferenceDrawer />

        {/* 429 Rate Limit Live Countdown Banner */}
        {isRateLimited && (
          <div
            role="alert"
            className="rounded-xl p-4 border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 text-amber-900 dark:text-amber-200 flex items-start gap-3 shadow-xs animate-in fade-in-50 duration-200"
          >
            <div className="p-1.5 rounded-lg bg-amber-100 dark:bg-amber-900/60 text-amber-800 dark:text-amber-300 shrink-0">
              <Clock className="w-5 h-5 animate-pulse" />
            </div>
            <div className="flex-1 space-y-1">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-bold">Rate Limit Cooling Down</h4>
                <span className="text-xs font-mono font-bold px-2 py-0.5 rounded bg-amber-200 dark:bg-amber-800/70 text-amber-900 dark:text-amber-100">
                  {rateLimitCountdown}s remaining
                </span>
              </div>
              <p className="text-xs sm:text-sm text-amber-800 dark:text-amber-300 leading-relaxed">
                {errorMessage ||
                  'You have exceeded the request quota for this key. Prompt submission is paused and will automatically resume once the timer expires.'}
              </p>
            </div>
          </div>
        )}

        {/* Low Confidence Warning Banner */}
        {warning && (
          <div
            role="status"
            className="rounded-xl p-3.5 border border-amber-200 dark:border-amber-800/60 bg-amber-50/70 dark:bg-amber-950/30 text-amber-800 dark:text-amber-300 flex items-start gap-2.5 text-xs sm:text-sm"
          >
            <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
            <div className="space-y-0.5">
              <span className="font-semibold">Retrieval Notice:</span> {warning}
            </div>
          </div>
        )}

        {/* Generic Error Banner */}
        {conversationState === 'error' && errorMessage && !isRateLimited && (
          <div
            role="alert"
            className="rounded-xl p-4 border border-red-200 dark:border-red-900/50 bg-red-50 dark:bg-red-950/30 text-red-900 dark:text-red-200 flex items-start gap-3"
          >
            <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <h4 className="text-sm font-bold">Unable to Complete Recommendation</h4>
              <p className="text-xs sm:text-sm text-red-800 dark:text-red-300 leading-relaxed">
                {errorMessage}
              </p>
            </div>
          </div>
        )}

        {/* Concierge Pitch Presentation Bubble */}
        {(pitch || isStreaming) && (
          <div className="pt-1">
            <ConciergePitch
              pitch={pitch}
              text={pitch}
              candidates={candidates}
              isStreaming={isStreaming}
              onSelectAnime={handleSelectAnime}
              onHoverAnime={(id) => setHoveredAnimeId(id)}
            />
          </div>
        )}

        {/* Anime Discovery Cards Section */}
        {candidates.length > 0 && (
          <ErrorBoundary resetKeys={[candidates]}>
            <div className="space-y-4 pt-2">
              <div className="flex items-center justify-between px-1">
                <h2 className="text-sm font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 flex items-center gap-2">
                  <Film className="w-4 h-4 text-brand" />
                  <span>Recommended Candidates ({candidates.length})</span>
                  {activeQuery && (
                    <span className="font-normal normal-case text-slate-400 truncate max-w-xs">
                      for &ldquo;{activeQuery}&rdquo;
                    </span>
                  )}
                </h2>
                {isStreaming && (
                  <div className="flex items-center gap-1.5 text-xs text-brand font-medium">
                    <span className="inline-block w-2 h-2 rounded-full bg-brand animate-ping" />
                    <span>Streaming commentary...</span>
                  </div>
                )}
              </div>

              {/* Candidate Card Grid (<1.5s TTFT Mount) */}
              <div className="grid grid-cols-1 gap-4">
                {candidates.map((anime) => (
                  <AnimeCard
                    key={anime.id}
                    anime={anime}
                    onMoreLikeThis={handleMoreLikeThis}
                    isHighlighted={highlightedAnimeId === anime.id || hoveredAnimeId === anime.id}
                  />
                ))}
              </div>
            </div>
          </ErrorBoundary>
        )}

        {/* Empty State / Welcome Guide when Idle and No Candidates */}
        {conversationState === 'idle' && candidates.length === 0 && (
          <div className="p-8 sm:p-12 text-center rounded-2xl border border-dashed border-slate-300 dark:border-dark-800 bg-white/50 dark:bg-dark-900/30 space-y-6">
            <div className="w-14 h-14 mx-auto rounded-2xl bg-brand/10 dark:bg-brand/20 text-brand flex items-center justify-center shadow-xs">
              <Compass className="w-7 h-7" />
            </div>
            <div className="space-y-2 max-w-md mx-auto">
              <h3 className="text-lg font-bold text-slate-900 dark:text-white">
                How it works
              </h3>
              <p className="text-xs sm:text-sm text-slate-500 dark:text-slate-400 leading-relaxed">
                Type any natural description into the prompt bar above or pick a starter mood. Candidate cards mount in less than 1.5 seconds, followed by real-time spoiler-free pitches.
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-left max-w-xl mx-auto pt-2">
              <div className="p-3.5 rounded-xl border border-slate-200 dark:border-dark-800 bg-white dark:bg-dark-900 space-y-1">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-900 dark:text-white">
                  <Zap className="w-3.5 h-3.5 text-brand" />
                  <span>Sub-1.5s Discovery</span>
                </div>
                <p className="text-[11px] text-slate-500 dark:text-slate-400">
                  Dual-stream SSE loads title metadata and cover images instantly before prose synthesis.
                </p>
              </div>

              <div className="p-3.5 rounded-xl border border-slate-200 dark:border-dark-800 bg-white dark:bg-dark-900 space-y-1">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-900 dark:text-white">
                  <Sparkles className="w-3.5 h-3.5 text-brand" />
                  <span>Grounded Pitches</span>
                </div>
                <p className="text-[11px] text-slate-500 dark:text-slate-400">
                  Streaming concierge commentary with proactive safety scrubbing to redact narrative spoilers.
                </p>
              </div>

              <div className="p-3.5 rounded-xl border border-slate-200 dark:border-dark-800 bg-white dark:bg-dark-900 space-y-1">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-900 dark:text-white">
                  <Film className="w-3.5 h-3.5 text-brand" />
                  <span>Memory & Exclusion</span>
                </div>
                <p className="text-[11px] text-slate-500 dark:text-slate-400">
                  Mark seen titles or dislike genres to automatically prune them from future recommendation turns.
                </p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
