// frontend/src/lib/analytics.ts
/**
 * Client-Side PostHog User Journey Analytics & Privacy Hardening.
 *
 * Enforces:
 * 1. PostHog initialised exclusively with client-safe env variables from config/env.ts.
 * 2. DOM autocapture disabled (autocapture: false).
 * 3. Client IP address capture strictly disabled (ip: false).
 * 4. Automatic pageview and session recording disabled.
 * 5. Explicit navigation funnels tracked:
 *    - landing_page_viewed
 *    - search_submitted
 *    - recommendation_rendered
 *    - recommendation_clicked
 * 6. Zero privacy leakage: raw search queries, user prompts, and synopsis texts
 *    are never sent to PostHog.
 */

import posthog from 'posthog-js';
import { env } from '../config/env';

let posthogInitialised = false;

export function initAnalytics(): void {
  if (typeof window === 'undefined') return;
  if (posthogInitialised) return;

  if (env.POSTHOG_KEY) {
    posthog.init(env.POSTHOG_KEY, {
      api_host: env.POSTHOG_HOST || 'https://eu.i.posthog.com',
      autocapture: false,
      ip: false, // Strict IP privacy: client IP capture disabled
      capture_pageview: false, // Explicit tracking only
      disable_session_recording: true,
      persistence: 'localStorage',
    });
    posthogInitialised = true;
  }
}

export function isAnalyticsInitialised(): boolean {
  return posthogInitialised;
}

export function trackLandingPageViewed(): void {
  if (!posthogInitialised) return;
  posthog.capture('landing_page_viewed');
}

export interface SearchSubmittedProperties {
  has_filters?: boolean;
  filter_count?: number;
  top_k?: number;
}

export function trackSearchSubmitted(properties?: SearchSubmittedProperties): void {
  if (!posthogInitialised) return;
  // Privacy assurance: only abstract boolean flags and counts; no search text
  posthog.capture('search_submitted', {
    has_filters: Boolean(properties?.has_filters),
    filter_count: properties?.filter_count ?? 0,
    top_k: properties?.top_k ?? 5,
  });
}

export interface RecommendationRenderedProperties {
  result_count?: number;
  has_recs?: boolean;
  cached?: boolean;
}

export function trackRecommendationRendered(properties?: RecommendationRenderedProperties): void {
  if (!posthogInitialised) return;
  // Privacy assurance: only candidate counts and cache flags; no title or synopsis strings
  posthog.capture('recommendation_rendered', {
    result_count: properties?.result_count ?? 0,
    has_recs: Boolean(properties?.has_recs),
    cached: Boolean(properties?.cached),
  });
}

export interface RecommendationClickedProperties {
  anime_id?: number;
  position?: number;
  format?: string;
}

export function trackRecommendationClicked(properties?: RecommendationClickedProperties): void {
  if (!posthogInitialised) return;
  // Privacy assurance: only item identifier and position index; no synopsis text
  posthog.capture('recommendation_clicked', {
    anime_id: properties?.anime_id,
    position: properties?.position,
    format: properties?.format,
  });
}
