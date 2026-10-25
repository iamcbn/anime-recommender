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
  Loader2,
  User,
} from 'lucide-react';
import type { ChatMessage, ConversationState } from '../types/chat';
import { useUserPreferences } from '../hooks/useUserPreferences';
import { streamChat } from '../lib/chatStream';
import { ChatInput } from '../components/chat/ChatInput';
import { AnimeCard } from '../components/chat/AnimeCard';
import { ConciergePitch } from '../components/chat/ConciergePitch';
import { PreferenceDrawer } from '../components/chat/PreferenceDrawer';
import { ErrorBoundary } from '../components/common/ErrorBoundary';
import {
  initAnalytics,
  trackLandingPageViewed,
  trackSearchSubmitted,
  trackRecommendationRendered,
  trackRecommendationClicked,
} from '../lib/analytics';

export const ChatPage: React.FC = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationState, setConversationState] = useState<ConversationState>('idle');
  const [query, setQuery] = useState('');
  const [activeQuery, setActiveQuery] = useState('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [rateLimitCountdown, setRateLimitCountdown] = useState<number>(0);
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);

  const abortControllerRef = useRef<AbortController | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
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

  // Initialise analytics and track landing page view
  useEffect(() => {
    initAnalytics();
    trackLandingPageViewed();
  }, []);

  // Clean up ongoing stream on unmount and ensure conversation state resets
  useEffect(() => {
    setConversationState('idle');
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }
      setConversationState('idle');
    };
  }, []);

  // Smoothly auto-scroll when new conversation turns are added or candidates mount
  const lastMessage = messages[messages.length - 1];
  const lastCandidateCount = lastMessage?.candidates?.length ?? 0;

  useEffect(() => {
    if (messages.length > 0) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages.length, lastCandidateCount]);

  const handleStop = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setConversationState('idle');
    setMessages((prev) =>
      prev.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m))
    );
  }, []);

  const handleSelectAnime = useCallback((animeId: number) => {
    trackRecommendationClicked({ anime_id: animeId });
    const el = document.getElementById(`anime-card-${animeId}`);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
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
      setErrorMessage(null);
      setHasMore(true);
      setIsLoadingMore(false);
      setQuery('');

      trackSearchSubmitted({
        has_filters: Boolean(preferences.disliked_genres?.length || preferences.seen_ids?.length),
        filter_count: (preferences.disliked_genres?.length || 0) + (preferences.seen_ids?.length || 0),
        top_k: 5,
      });

      const now = Date.now();
      const userMsgId = `user-${now}`;
      const asstMsgId = `asst-${now + 1}`;

      const userMsg: ChatMessage = {
        id: userMsgId,
        role: 'user',
        text: target,
        timestamp: now,
      };

      const asstMsg: ChatMessage = {
        id: asstMsgId,
        role: 'assistant',
        text: '',
        candidates: [],
        isStreaming: true,
        timestamp: now + 1,
      };

      // Append user message and active assistant placeholder to the conversation feed
      setMessages((prev) => [...prev, userMsg, asstMsg]);

      // Serialise previous conversation turns for LLM context
      const conversationHistory = messages.map((m) => ({
        role: m.role,
        content: m.text || '',
      }));

      // Gather seen IDs across preferences and already recommended titles
      const allPriorCandidateIds = messages.flatMap((m) =>
        (m.candidates || []).map((c) => c.id)
      );
      const cumulativeSeen = Array.from(
        new Set([...preferences.seen_ids, ...allPriorCandidateIds])
      );

      try {
        await streamChat({
          query: target,
          top_k: 5,
          allow_adult: preferences.allow_adult,
          seen_ids: cumulativeSeen,
          disliked_genres: preferences.disliked_genres,
          session_id: sessionId,
          conversation_history: conversationHistory,
          signal: controller.signal,
          onMetadata: (metadata) => {
            const fetched = metadata.candidates || [];
            const recId = metadata.recommendation_id || metadata.request_id;
            trackRecommendationRendered({
              result_count: fetched.length,
              has_recs: fetched.length > 0,
            });
            setMessages((prev) =>
              prev.map((m) =>
                m.id === asstMsgId
                  ? {
                      ...m,
                      candidates: fetched,
                      timings: metadata.timings || m.timings,
                      recommendation_id: recId,
                      request_id: recId,
                    }
                  : m
              )
            );
            if (fetched.length < 5) {
              setHasMore(false);
            }
            if (metadata.session_id) {
              setSessionId(metadata.session_id);
            }
          },
          onToken: (chunk, animeId) => {
            if (animeId !== undefined) {
              return;
            }
            setMessages((prev) =>
              prev.map((m) =>
                m.id === asstMsgId
                  ? {
                      ...m,
                      text: (m.text || '') + chunk,
                    }
                  : m
              )
            );
          },
          onWarning: (w) => {
            const warningText = w.detail || w.warning || 'Low retrieval confidence';
            setMessages((prev) =>
              prev.map((m) =>
                m.id === asstMsgId
                  ? {
                      ...m,
                      warning: warningText,
                    }
                  : m
              )
            );
          },
          onDone: (done) => {
            setConversationState('completed');
            setMessages((prev) =>
              prev.map((m) =>
                m.id === asstMsgId
                  ? {
                      ...m,
                      isStreaming: false,
                      timings: done.timings || m.timings,
                    }
                  : m
              )
            );
            if (done.session_id) {
              setSessionId(done.session_id);
            }
          },
          onError: (err) => {
            const errorDetail =
              err.message || err.detail || 'Failed to complete recommendation search.';
            setMessages((prev) =>
              prev.map((m) =>
                m.id === asstMsgId
                  ? {
                      ...m,
                      isStreaming: false,
                      error: errorDetail,
                    }
                  : m
              )
            );
            if (err.status === 429) {
              const seconds = err.retryAfter && err.retryAfter > 0 ? err.retryAfter : 60;
              setConversationState('rate_limited');
              setRateLimitCountdown(seconds);
              setErrorMessage(err.message || 'Rate limit reached. Please wait a moment.');
            } else {
              setConversationState('error');
              setErrorMessage(errorDetail);
            }
          },
        });
      } finally {
        if (abortControllerRef.current === controller) {
          abortControllerRef.current = null;
        }
      }
    },
    [query, conversationState, rateLimitCountdown, preferences, sessionId, messages]
  );

  const handleMoreLikeThis = useCallback(
    (title: string) => {
      const morePrompt = `More like ${title}`;
      handleSearch(morePrompt);
    },
    [handleSearch]
  );

  const handleLoadMore = useCallback(async () => {
    if (isLoadingMore || !hasMore || !activeQuery) return;
    if (conversationState === 'rate_limited' || rateLimitCountdown > 0) return;

    const latestAsst = [...messages].reverse().find((m) => m.role === 'assistant');
    if (!latestAsst) return;

    setIsLoadingMore(true);

    const allCandidateIds = messages.flatMap((m) =>
      (m.candidates || []).map((c) => c.id)
    );
    const cumulativeSeen = Array.from(
      new Set([...preferences.seen_ids, ...allCandidateIds])
    );
    const currentOffset = (latestAsst.candidates || []).length;

    let receivedCount = 0;

    try {
      await streamChat({
        query: activeQuery,
        top_k: 5,
        offset: currentOffset,
        allow_adult: preferences.allow_adult,
        seen_ids: cumulativeSeen,
        disliked_genres: preferences.disliked_genres,
        session_id: sessionId,
        onMetadata: (metadata) => {
          const newCandidates = metadata.candidates || [];
          receivedCount = newCandidates.length;
          if (newCandidates.length > 0) {
            setMessages((prev) =>
              prev.map((m) => {
                if (m.id === latestAsst.id) {
                  const existingIds = new Set((m.candidates || []).map((c) => c.id));
                  const fresh = newCandidates.filter((c) => !existingIds.has(c.id));
                  return {
                    ...m,
                    candidates: [...(m.candidates || []), ...fresh],
                  };
                }
                return m;
              })
            );
          }
          if (metadata.session_id) {
            setSessionId(metadata.session_id);
          }
        },
        onDone: (done) => {
          if (receivedCount === 0 || receivedCount < 5) {
            setHasMore(false);
          }
          if (done.session_id) {
            setSessionId(done.session_id);
          }
        },
        onError: (err) => {
          if (err.status === 429) {
            const seconds = err.retryAfter && err.retryAfter > 0 ? err.retryAfter : 60;
            setConversationState('rate_limited');
            setRateLimitCountdown(seconds);
            setErrorMessage(err.message || 'Rate limit reached. Please wait a moment.');
          } else {
            setErrorMessage(err.message || err.detail || 'Failed to load additional recommendations.');
          }
        },
      });
    } finally {
      setIsLoadingMore(false);
    }
  }, [
    isLoadingMore,
    hasMore,
    activeQuery,
    conversationState,
    rateLimitCountdown,
    messages,
    preferences,
    sessionId,
  ]);

  const isStreaming = conversationState === 'streaming';
  const isRateLimited = conversationState === 'rate_limited' || rateLimitCountdown > 0;
  const latestAssistantIndex = messages.map((m) => m.role).lastIndexOf('assistant');

  return (
    <div className="min-h-[calc(100vh-3.5rem)] bg-slate-50/50 dark:bg-dark-950 py-8 px-4 sm:px-6 lg:px-8">
      <div className="max-w-4xl mx-auto space-y-6">
        {/* Hero / Header Section */}
        <div className="text-center space-y-2.5">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-brand/10 text-brand dark:bg-brand/20 dark:text-brand-light">
            <Sparkles className="w-3.5 h-3.5" />
            <span>AI Conversational Discovery</span>
          </div>
          <h1 className="text-3xl sm:text-4xl font-extrabold text-slate-900 dark:text-white tracking-tight">
            Find Your Next Anime Obsession
          </h1>
          <p className="text-sm sm:text-base text-slate-600 dark:text-slate-400 max-w-xl mx-auto leading-relaxed">
            Describe a mood, character archetype, or complex trope. Our neural concierge matches and pitches personalised titles in real time.
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

        {/* Generic Top-level Error Banner when no conversation turns exist */}
        {conversationState === 'error' && errorMessage && !isRateLimited && messages.length === 0 && (
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

        {/* Conversational Message Feed */}
        {messages.length > 0 && (
          <div className="space-y-6 pt-2 pb-6" role="log" aria-label="Conversation Feed">
            {messages.map((message, index) => {
              const isLatestAssistant = index === latestAssistantIndex;

              if (message.role === 'user') {
                return (
                  <div
                    key={message.id}
                    className="flex justify-end items-start gap-3"
                  >
                    <div className="max-w-[85%] sm:max-w-[75%] rounded-2xl rounded-tr-xs px-4 py-3 bg-brand text-white shadow-xs">
                      <p className="text-sm sm:text-base leading-relaxed whitespace-pre-wrap font-medium">
                        {message.text}
                      </p>
                    </div>
                    <div
                      className="w-8 h-8 rounded-full bg-brand/10 dark:bg-brand/20 text-brand dark:text-brand-light border border-brand/20 flex items-center justify-center shrink-0 shadow-xs mt-1"
                      aria-label="User"
                    >
                      <User className="w-4 h-4" />
                    </div>
                  </div>
                );
              }

              return (
                <div key={message.id} className="flex items-start gap-3">
                  <div
                    className="w-8 h-8 rounded-full bg-brand/10 dark:bg-brand/20 text-brand dark:text-brand-light border border-brand/20 flex items-center justify-center shrink-0 shadow-xs mt-1"
                    aria-label="AI Concierge"
                  >
                    <Sparkles className="w-4 h-4" />
                  </div>
                  <div className="flex-1 space-y-4 min-w-0">
                    {/* Low Confidence Notice */}
                    {message.warning && (
                      <div
                        role="status"
                        className="rounded-xl p-3.5 border border-amber-200 dark:border-amber-800/60 bg-amber-50/70 dark:bg-amber-950/30 text-amber-800 dark:text-amber-300 flex items-start gap-2.5 text-xs sm:text-sm"
                      >
                        <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
                        <div className="space-y-0.5">
                          <span className="font-semibold">Retrieval Notice:</span> {message.warning}
                        </div>
                      </div>
                    )}

                    {/* Turn Error Notice */}
                    {message.error && (
                      <div
                        role="alert"
                        className="rounded-xl p-3.5 border border-red-200 dark:border-red-900/50 bg-red-50 dark:bg-red-950/30 text-red-900 dark:text-red-200 flex items-start gap-2.5 text-xs sm:text-sm"
                      >
                        <AlertCircle className="w-4 h-4 text-red-600 dark:text-red-400 shrink-0 mt-0.5" />
                        <div className="space-y-0.5">
                          <span className="font-semibold">Generation Notice:</span> {message.error}
                        </div>
                      </div>
                    )}

                    {/* Conversational Text Response Bubble */}
                    {Boolean(message.text && message.text.trim()) && (
                      <div className="rounded-2xl rounded-tl-xs px-4 py-3 bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 text-slate-800 dark:text-slate-200 text-sm sm:text-base leading-relaxed shadow-xs">
                        <ConciergePitch
                          plain
                          text={message.text}
                          candidates={message.candidates}
                          isStreaming={message.isStreaming}
                          onSelectAnime={handleSelectAnime}
                        />
                      </div>
                    )}

                    {/* Neural Search Progress Indicator */}
                    {message.isStreaming &&
                      (!message.candidates || message.candidates.length === 0) && (
                        <div className="flex items-center gap-2 text-xs sm:text-sm text-brand font-medium p-4 bg-white dark:bg-dark-900 rounded-2xl border border-slate-200 dark:border-dark-800 shadow-xs">
                          <Loader2 className="w-4 h-4 animate-spin text-brand shrink-0" />
                          <span>Searching neural index and preparing personalized recommendations...</span>
                        </div>
                      )}

                    {/* Anime Discovery Cards Section */}
                    {message.candidates && message.candidates.length > 0 && (
                      <ErrorBoundary resetKeys={[message.candidates]}>
                        <div className="space-y-4 pt-1">
                          <div className="flex items-center justify-between px-1">
                            <h2 className="text-sm font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 flex items-center gap-2">
                              <Film className="w-4 h-4 text-brand" />
                              <span>Recommended Candidates ({message.candidates.length})</span>
                            </h2>
                          </div>

                          <div className="grid grid-cols-1 gap-4">
                            {message.candidates.map((anime, index) => (
                              <AnimeCard
                                key={anime.id}
                                anime={anime}
                                query={activeQuery}
                                recommendationId={message.recommendation_id}
                                position={index}
                                onMoreLikeThis={handleMoreLikeThis}
                              />
                            ))}
                          </div>

                          {/* Offset-based Load More Recommendations Button (Latest assistant turn only) */}
                          {isLatestAssistant && hasMore && (
                            <div className="flex justify-center pt-2 pb-2">
                              <button
                                type="button"
                                onClick={handleLoadMore}
                                disabled={isLoadingMore || isStreaming}
                                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl font-medium text-sm text-slate-700 dark:text-slate-200 bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 shadow-xs hover:bg-slate-50 dark:hover:bg-dark-800 hover:border-slate-300 dark:hover:border-dark-700 transition-all focus:outline-none focus:ring-2 focus:ring-brand focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed select-none"
                              >
                                {isLoadingMore ? (
                                  <>
                                    <Loader2 className="w-4 h-4 animate-spin text-brand" />
                                    <span>Loading more recommendations...</span>
                                  </>
                                ) : (
                                  <>
                                    <Sparkles className="w-4 h-4 text-brand" />
                                    <span>Load More Recommendations</span>
                                  </>
                                )}
                              </button>
                            </div>
                          )}
                        </div>
                      </ErrorBoundary>
                    )}
                  </div>
                </div>
              );
            })}
            <div ref={messagesEndRef} />
          </div>
        )}

        {/* Empty State / Welcome Guide when Idle and No Messages */}
        {messages.length === 0 && (
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
