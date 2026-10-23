// frontend/src/test/apiContract.test.ts
/**
 * Frontend contract verification test suite for Sprint 4.
 *
 * Verifies that application UI components correctly render canonical API response fixtures
 * defined in contractMocks.ts without layout regressions, runtime exceptions, or missing fields.
 *
 * Adheres strictly to British English documentation standards with zero em-dashes.
 */

import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import { KeyListTable } from '../components/developers/KeyListTable';
import { KeyQuotaBanner } from '../components/developers/KeyQuotaBanner';
import { LlmUsageView } from '../components/admin/LlmUsageView';
import { TelemetryTable } from '../components/admin/TelemetryTable';

import {
  mockDevKeysListResponse,
  mockCurrentBudgetResponse,
  mockDailyUsageResponse,
  mockTelemetryLogsResponse,
} from './contractMocks';
import type { UseLlmUsageResult } from '../hooks/useLlmUsage';

describe('Frontend API Contract Suite', () => {
  describe('KeyListTable contract rendering', () => {
    it('renders developer keys list with correct names, prefixes, and lifecycle badges', () => {
      /**
       * Verifies that KeyListTable displays all keys from mockDevKeysListResponse with
       * corresponding key names, masked prefixes, and status badges (Active vs Revoked).
       * This behaviour protects developer portal usability and ensures credential visibility.
       */
      const mockOnRevoke = vi.fn();

      render(
        React.createElement(KeyListTable, {
          keys: mockDevKeysListResponse.keys,
          isLoading: false,
          onRevokeClick: mockOnRevoke,
        })
      );

      // Verify key names are rendered
      expect(screen.getByText('Production Web App')).toBeInTheDocument();
      expect(screen.getByText('Staging Server')).toBeInTheDocument();
      expect(screen.getByText('Deprecated CLI Client')).toBeInTheDocument();

      // Verify key prefixes are rendered in monospace format
      expect(screen.getByText('ar_live_a1b2c3d4')).toBeInTheDocument();
      expect(screen.getByText('ar_live_e5f60718')).toBeInTheDocument();
      expect(screen.getByText('ar_live_9a8b7c6d')).toBeInTheDocument();

      // Verify status badges: 2 Active, 1 Revoked
      const activeBadges = screen.getAllByText('Active');
      expect(activeBadges).toHaveLength(2);
      expect(screen.getByText('Revoked')).toBeInTheDocument();

      // Verify clicking revoke invokes callback with the correct key item
      const revokeButtons = screen.getAllByTitle('Revoke key');
      expect(revokeButtons.length).toBeGreaterThanOrEqual(2);
      fireEvent.click(revokeButtons[0]);
      expect(mockOnRevoke).toHaveBeenCalledWith(mockDevKeysListResponse.keys[0]);
    });

    it('renders empty placeholder state when zero keys exist', () => {
      /**
       * Verifies that KeyListTable renders a friendly onboarding empty state when
       * the developer has no registered API keys.
       * This behaviour protects user experience for newly onboarded developers.
       */
      render(
        React.createElement(KeyListTable, {
          keys: [],
          isLoading: false,
          onRevokeClick: vi.fn(),
        })
      );

      expect(screen.getByText('No API keys created yet')).toBeInTheDocument();
      expect(
        screen.getByText('Click Create API Key above to generate your first token.')
      ).toBeInTheDocument();
    });
  });

  describe('KeyQuotaBanner contract rendering', () => {
    it('displays active key count and quota limit correctly when under capacity', () => {
      /**
       * Verifies that KeyQuotaBanner accurately displays current active key count and maximum
       * allowance without showing a limit warning when capacity is available.
       * This behaviour protects quota transparency for developers.
       */
      render(React.createElement(KeyQuotaBanner, { activeCount: 2, maxAllowed: 5 }));

      expect(screen.getByText(/Active keys: 2 \/ 5/i)).toBeInTheDocument();
      expect(screen.getByText(/Rate limit: 20 req\/min/i)).toBeInTheDocument();
      expect(screen.queryByText(/Limit reached/i)).not.toBeInTheDocument();
    });

    it('displays warning banner when active key quota limit is reached', () => {
      /**
       * Verifies that KeyQuotaBanner presents an alert warning when the active key count
       * reaches the maximum ceiling of 5 keys.
       * This behaviour protects users by explaining why key creation is blocked before attempting it.
       */
      render(React.createElement(KeyQuotaBanner, { activeCount: 5, maxAllowed: 5 }));

      expect(screen.getByText(/Active keys: 5 \/ 5/i)).toBeInTheDocument();
      expect(
        screen.getByText(/Limit reached. Revoke an unused key before creating another./i)
      ).toBeInTheDocument();
    });
  });

  describe('LlmUsageView contract rendering', () => {
    it('renders live budget gauges and daily aggregation table with mock responses', () => {
      /**
       * Verifies that LlmUsageView renders summary metrics, live budget ceiling gauges for all
       * three layers (NLI, Retrieval, Presentation), and the historical daily token table.
       * This behaviour protects operational observability and LLM cost monitoring for administrators.
       */
      const mockUsageData: UseLlmUsageResult = {
        dailyUsage: mockDailyUsageResponse,
        budget: mockCurrentBudgetResponse,
        isLoading: false,
        error: null,
        days: 7,
        selectedLayer: 'all',
        setDays: vi.fn(),
        setSelectedLayer: vi.fn(),
        refetch: vi.fn().mockResolvedValue(undefined),
        summary: {
          todayTokens: 225500,
          todayCost: 0.069,
          totalTokensInRange: 306300,
          totalCostInRange: 0.0735,
          totalRequestsInRange: 525,
          healthyLayersCount: 2,
          softLimitCount: 1,
          hardLimitCount: 0,
        },
      };

      render(React.createElement(LlmUsageView, { usageData: mockUsageData }));

      // Top summary cards
      expect(screen.getByText('Tokens Today')).toBeInTheDocument();
      expect(screen.getByText('Est. Cost Today')).toBeInTheDocument();
      expect(screen.getByText('Total LLM Requests')).toBeInTheDocument();
      expect(screen.getByText('Layer Health Status')).toBeInTheDocument();

      // Budget gauge cards
      expect(screen.getByText('NLI (Query Understanding)')).toBeInTheDocument();
      expect(screen.getByText('Hybrid Retrieval (HyDE Expansion)')).toBeInTheDocument();
      expect(screen.getByText('Presentation (Taste Concierge)')).toBeInTheDocument();

      // Verify soft limit badge rendered for retrieval layer (84% usage)
      expect(screen.getByText('80% Soft')).toBeInTheDocument();

      // Daily table column headers
      expect(screen.getByText('Date')).toBeInTheDocument();
      expect(screen.getByText('Prompt Tokens')).toBeInTheDocument();
      expect(screen.getByText('Completion Tokens')).toBeInTheDocument();
      expect(screen.getByText('Total Tokens')).toBeInTheDocument();
      expect(screen.getByText('Est. Cost (USD)')).toBeInTheDocument();

      // Verify daily row content
      expect(screen.getAllByText('2026-10-23').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('2026-10-22')).toBeInTheDocument();
    });
  });

  describe('TelemetryTable contract rendering', () => {
    it('renders recommendation logs with query, latency, status badges, and inspect action', () => {
      /**
       * Verifies that TelemetryTable renders recommendation telemetry rows with query texts,
       * endpoint labels, source tags, HTTP status codes, and executes inspect callbacks on demand.
       * This behaviour protects administrative debugging and query inspection capabilities.
       */
      const mockOnInspect = vi.fn();
      const mockOnPageChange = vi.fn();

      render(
        React.createElement(TelemetryTable, {
          logs: mockTelemetryLogsResponse,
          isLoading: false,
          page: 0,
          pageSize: 25,
          totalCount: mockTelemetryLogsResponse.length,
          onPageChange: mockOnPageChange,
          onInspectClick: mockOnInspect,
        })
      );

      // Verify query texts
      expect(screen.getByText('cyberpunk detective thriller')).toBeInTheDocument();
      expect(screen.getByText('psychological mecha drama')).toBeInTheDocument();

      // Verify endpoint and source badges
      expect(screen.getByText('recommend')).toBeInTheDocument();
      expect(screen.getByText('admin_recommend')).toBeInTheDocument();
      expect(screen.getByText('user')).toBeInTheDocument();
      expect(screen.getByText('admin_eval')).toBeInTheDocument();

      // Verify status 'ok' badges
      const statusBadges = screen.getAllByText('ok');
      expect(statusBadges).toHaveLength(2);

      // Verify latency formatted text
      expect(screen.getByText('185 ms')).toBeInTheDocument();
      expect(screen.getByText('321 ms')).toBeInTheDocument();

      // Verify inspect button triggers callback with selected log item
      const inspectButtons = screen.getAllByText('Inspect');
      expect(inspectButtons).toHaveLength(2);
      fireEvent.click(inspectButtons[0]);
      expect(mockOnInspect).toHaveBeenCalledWith(mockTelemetryLogsResponse[0]);
    });

    it('renders empty placeholder state when zero logs match filters', () => {
      /**
       * Verifies that TelemetryTable renders a helpful empty state when query filters return no records.
       * This behaviour protects admin experience during search and filter operations.
       */
      render(
        React.createElement(TelemetryTable, {
          logs: [],
          isLoading: false,
          page: 0,
          pageSize: 25,
          totalCount: 0,
          onPageChange: vi.fn(),
          onInspectClick: vi.fn(),
        })
      );

      expect(screen.getByText('No Telemetry Logs Found')).toBeInTheDocument();
      expect(
        screen.getByText(
          'No records match your selected filters. Adjust your source, endpoint, or date range.'
        )
      ).toBeInTheDocument();
    });
  });
});
