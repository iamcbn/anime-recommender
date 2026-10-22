// frontend/src/components/admin/LlmUsageView.tsx
import React from 'react';
import {
  Zap,
  DollarSign,
  Activity,
  ShieldCheck,
  AlertTriangle,
  AlertOctagon,
  RefreshCw,
  Cpu,
  Layers,
  Clock,
  Search,
  MessageSquare,
} from 'lucide-react';
import { Button } from '../common/Button';
import { Badge } from '../common/Badge';
import type { UseLlmUsageResult } from '../../hooks/useLlmUsage';

export interface LlmUsageViewProps {
  usageData: UseLlmUsageResult;
}

export const LlmUsageView: React.FC<LlmUsageViewProps> = ({ usageData }) => {
  const {
    dailyUsage,
    budget,
    isLoading,
    days,
    selectedLayer,
    setDays,
    setSelectedLayer,
    refetch,
    summary,
  } = usageData;

  const getLayerBadgeVariant = (layer: string): 'info' | 'warning' | 'success' | 'neutral' => {
    switch (layer.toLowerCase()) {
      case 'nli':
        return 'info';
      case 'retrieval':
        return 'warning';
      case 'presentation':
        return 'success';
      default:
        return 'neutral';
    }
  };

  const getLayerIcon = (layer: string) => {
    switch (layer.toLowerCase()) {
      case 'nli':
        return <Search className="w-4 h-4 text-sky-500" />;
      case 'retrieval':
        return <Layers className="w-4 h-4 text-amber-500" />;
      case 'presentation':
        return <MessageSquare className="w-4 h-4 text-emerald-500" />;
      default:
        return <Cpu className="w-4 h-4 text-slate-500" />;
    }
  };

  const getLayerTitle = (layer: string) => {
    switch (layer.toLowerCase()) {
      case 'nli':
        return 'NLI (Query Understanding)';
      case 'retrieval':
        return 'Hybrid Retrieval (HyDE Expansion)';
      case 'presentation':
        return 'Presentation (Taste Concierge)';
      default:
        return layer.toUpperCase();
    }
  };

  const getLayerDescription = (layer: string) => {
    switch (layer.toLowerCase()) {
      case 'nli':
        return 'Query rewrite & intent extraction ($0 on turn 1 bypass)';
      case 'retrieval':
        return 'HyDE hypothetical synopsis vector expansion';
      case 'presentation':
        return 'Dual-stream conversational discovery pitch';
      default:
        return '';
    }
  };

  return (
    <div className="flex flex-col gap-6">
      {/* 1. Top Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Tokens Today */}
        <div className="p-4 bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-xl shadow-xs flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-400">
            <Zap className="w-5 h-5" />
          </div>
          <div className="min-w-0 flex-1">
            <span className="text-xs text-slate-500 dark:text-slate-400 block truncate">Tokens Today</span>
            <h3 className="text-xl font-bold text-slate-900 dark:text-white truncate">
              {summary.todayTokens.toLocaleString()}
            </h3>
            <span className="text-[11px] text-slate-400 dark:text-slate-500">
              {summary.totalTokensInRange.toLocaleString()} in {days}d window
            </span>
          </div>
        </div>

        {/* Est. Cost Today */}
        <div className="p-4 bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-xl shadow-xs flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400">
            <DollarSign className="w-5 h-5" />
          </div>
          <div className="min-w-0 flex-1">
            <span className="text-xs text-slate-500 dark:text-slate-400 block truncate">Est. Cost Today</span>
            <h3 className="text-xl font-bold text-slate-900 dark:text-white truncate">
              ${summary.todayCost.toFixed(4)}
            </h3>
            <span className="text-[11px] text-slate-400 dark:text-slate-500">
              ${summary.totalCostInRange.toFixed(4)} in {days}d window
            </span>
          </div>
        </div>

        {/* Total Requests In Range */}
        <div className="p-4 bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-xl shadow-xs flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-sky-50 text-sky-600 dark:bg-sky-500/10 dark:text-sky-400">
            <Activity className="w-5 h-5" />
          </div>
          <div className="min-w-0 flex-1">
            <span className="text-xs text-slate-500 dark:text-slate-400 block truncate">Total LLM Requests</span>
            <h3 className="text-xl font-bold text-slate-900 dark:text-white truncate">
              {summary.totalRequestsInRange.toLocaleString()}
            </h3>
            <span className="text-[11px] text-slate-400 dark:text-slate-500">
              Over last {days} {days === 1 ? 'day' : 'days'}
            </span>
          </div>
        </div>

        {/* Layer Health Status */}
        <div className="p-4 bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-xl shadow-xs flex items-center gap-3">
          <div
            className={`p-2.5 rounded-lg ${
              summary.hardLimitCount > 0
                ? 'bg-red-50 text-red-600 dark:bg-red-500/10 dark:text-red-400'
                : summary.softLimitCount > 0
                ? 'bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-400'
                : 'bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400'
            }`}
          >
            {summary.hardLimitCount > 0 ? (
              <AlertOctagon className="w-5 h-5" />
            ) : summary.softLimitCount > 0 ? (
              <AlertTriangle className="w-5 h-5" />
            ) : (
              <ShieldCheck className="w-5 h-5" />
            )}
          </div>
          <div className="min-w-0 flex-1">
            <span className="text-xs text-slate-500 dark:text-slate-400 block truncate">Layer Health Status</span>
            <h3 className="text-sm font-bold text-slate-900 dark:text-white truncate">
              {summary.hardLimitCount > 0
                ? `${summary.hardLimitCount} Hard Ceiling Hit`
                : summary.softLimitCount > 0
                ? `${summary.softLimitCount} Soft Limit Warning`
                : 'All 3 Layers Healthy'}
            </h3>
            <span className="text-[11px] text-slate-400 dark:text-slate-500">
              {summary.hardLimitCount > 0
                ? 'Graceful zero-token fallback active'
                : 'Within safe token budget'}
            </span>
          </div>
        </div>
      </div>

      {/* 2. Live Daily Budget Gauges */}
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-white flex items-center gap-2">
            <Cpu className="w-4 h-4 text-indigo-500" />
            Daily Token Ceilings &amp; Budget Guard
          </h2>
          <span className="text-xs text-slate-500 dark:text-slate-400">
            Resets daily at 00:00 UTC (80% Soft Alert, 100% Graceful Degradation)
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {['nli', 'retrieval', 'presentation'].map((layerKey) => {
            const b = budget?.[layerKey] || {
              layer: layerKey,
              current_usage: 0,
              limit: layerKey === 'nli' ? 100000 : layerKey === 'retrieval' ? 200000 : 300000,
              remaining: layerKey === 'nli' ? 100000 : layerKey === 'retrieval' ? 200000 : 300000,
              soft_limit_hit: false,
              hard_limit_hit: false,
              usage_ratio: 0.0,
            };

            const percentage = Math.min(100, Math.round(b.usage_ratio * 100));

            return (
              <div
                key={layerKey}
                className="p-4 bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-xl shadow-xs flex flex-col justify-between gap-3"
              >
                <div>
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <div className="flex items-center gap-2">
                      {getLayerIcon(layerKey)}
                      <span className="text-xs font-semibold text-slate-900 dark:text-white">
                        {getLayerTitle(layerKey)}
                      </span>
                    </div>

                    {b.hard_limit_hit ? (
                      <Badge variant="danger" size="sm">Hard Ceiling</Badge>
                    ) : b.soft_limit_hit ? (
                      <Badge variant="warning" size="sm">80% Soft</Badge>
                    ) : (
                      <Badge variant="success" size="sm">Normal</Badge>
                    )}
                  </div>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400">
                    {getLayerDescription(layerKey)}
                  </p>
                </div>

                <div>
                  {/* Numbers row */}
                  <div className="flex items-baseline justify-between text-xs mb-1.5 font-mono">
                    <span className="text-slate-900 dark:text-white font-medium">
                      {b.current_usage.toLocaleString()}{' '}
                      <span className="text-slate-400 font-normal">/ {b.limit.toLocaleString()}</span>
                    </span>
                    <span
                      className={`font-semibold ${
                        b.hard_limit_hit
                          ? 'text-red-600 dark:text-red-400'
                          : b.soft_limit_hit
                          ? 'text-amber-600 dark:text-amber-400'
                          : 'text-slate-700 dark:text-slate-300'
                      }`}
                    >
                      {percentage}%
                    </span>
                  </div>

                  {/* Progress bar container */}
                  <div className="relative w-full h-2.5 bg-slate-100 dark:bg-dark-950 rounded-full overflow-hidden border border-slate-200/60 dark:border-dark-800">
                    {/* 80% soft limit notch mark */}
                    <div
                      className="absolute top-0 bottom-0 w-0.5 bg-amber-400/80 dark:bg-amber-500/80 z-10"
                      style={{ left: '80%' }}
                      title="80% Soft Alert Threshold"
                    />

                    {/* Progress Fill */}
                    <div
                      className={`h-full transition-all duration-300 rounded-full ${
                        b.hard_limit_hit
                          ? 'bg-red-500 dark:bg-red-400'
                          : b.soft_limit_hit
                          ? 'bg-amber-500 dark:bg-amber-400'
                          : 'bg-emerald-500 dark:bg-emerald-400'
                      }`}
                      style={{ width: `${percentage}%` }}
                    />
                  </div>

                  {/* Subtext info */}
                  <div className="flex items-center justify-between text-[10px] text-slate-400 dark:text-slate-500 mt-1.5 font-mono">
                    <span>{b.remaining.toLocaleString()} remaining</span>
                    <span>Soft limit: {(b.limit * 0.8).toLocaleString()}</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 3. Filter Toolbar */}
      <div className="p-4 bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-xl shadow-xs flex flex-wrap items-center justify-between gap-4">
        {/* Date Range Options */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500 dark:text-slate-400 font-medium mr-1">Range:</span>
          {[
            { label: 'Today', value: 1 },
            { label: 'Last 7 Days', value: 7 },
            { label: 'Last 30 Days', value: 30 },
          ].map((opt) => (
            <button
              key={opt.value}
              onClick={() => setDays(opt.value)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                days === opt.value
                  ? 'bg-indigo-600 text-white shadow-xs'
                  : 'bg-slate-100 dark:bg-dark-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-dark-700'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {/* Layer Filters */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500 dark:text-slate-400 font-medium mr-1">Layer:</span>
          {[
            { label: 'All Layers', value: 'all' },
            { label: 'NLI', value: 'nli' },
            { label: 'Retrieval', value: 'retrieval' },
            { label: 'Presentation', value: 'presentation' },
          ].map((opt) => (
            <button
              key={opt.value}
              onClick={() => setSelectedLayer(opt.value)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                selectedLayer === opt.value
                  ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900 shadow-xs'
                  : 'bg-slate-100 dark:bg-dark-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-dark-700'
              }`}
            >
              {opt.label}
            </button>
          ))}

          {/* Refresh Button */}
          <Button
            variant="secondary"
            size="sm"
            onClick={refetch}
            isLoading={isLoading}
            icon={<RefreshCw className="w-3.5 h-3.5" />}
          >
            Refresh
          </Button>
        </div>
      </div>

      {/* 4. Table / Breakdown View */}
      <div className="bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-xl shadow-xs overflow-hidden">
        <div className="px-5 py-3.5 border-b border-slate-200 dark:border-dark-800 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
              Daily Usage &amp; Cost Breakdown
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              gpt-5.4-mini pricing ($0.15 / 1M prompt tokens, $0.60 / 1M completion tokens)
            </p>
          </div>
          <span className="text-xs text-slate-500 dark:text-slate-400 font-mono">
            {dailyUsage.length} {dailyUsage.length === 1 ? 'record' : 'records'}
          </span>
        </div>

        {isLoading && dailyUsage.length === 0 ? (
          <div className="py-16 flex flex-col items-center justify-center text-slate-500 dark:text-slate-400 gap-3">
            <Clock className="w-6 h-6 animate-spin text-indigo-500" />
            <span className="text-xs">Aggregating telemetry records...</span>
          </div>
        ) : dailyUsage.length === 0 ? (
          <div className="py-16 text-center text-slate-500 dark:text-slate-400 flex flex-col items-center justify-center gap-2">
            <Layers className="w-8 h-8 text-slate-300 dark:text-slate-600" />
            <span className="text-sm font-medium">No LLM usage records found</span>
            <span className="text-xs max-w-sm text-slate-400">
              No queries logged in the selected {days}-day period for layer &apos;{selectedLayer}&apos;.
            </span>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-600 dark:text-slate-300">
              <thead className="bg-slate-50 dark:bg-dark-950 text-slate-500 dark:text-slate-400 font-medium uppercase text-[10px] tracking-wider border-b border-slate-200 dark:border-dark-800">
                <tr>
                  <th scope="col" className="px-4 py-3">Date</th>
                  <th scope="col" className="px-4 py-3">Layer</th>
                  <th scope="col" className="px-4 py-3 text-right">Requests</th>
                  <th scope="col" className="px-4 py-3 text-right">Prompt Tokens</th>
                  <th scope="col" className="px-4 py-3 text-right">Completion Tokens</th>
                  <th scope="col" className="px-4 py-3 text-right">Total Tokens</th>
                  <th scope="col" className="px-4 py-3 text-center">Cache Hits</th>
                  <th scope="col" className="px-4 py-3 text-center">Fallbacks</th>
                  <th scope="col" className="px-4 py-3 text-right">Est. Cost (USD)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 dark:divide-dark-800 font-mono">
                {dailyUsage.map((item, idx) => (
                  <tr
                    key={`${item.date}-${item.layer}-${idx}`}
                    className="hover:bg-slate-50/70 dark:hover:bg-dark-800/50 transition-colors"
                  >
                    <td className="px-4 py-3 whitespace-nowrap text-slate-900 dark:text-white font-medium">
                      {item.date}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap font-sans">
                      <Badge variant={getLayerBadgeVariant(item.layer)} size="sm">
                        {item.layer.toUpperCase()}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-right">
                      {item.request_count.toLocaleString()}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-right text-slate-500 dark:text-slate-400">
                      {item.prompt_tokens.toLocaleString()}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-right text-slate-500 dark:text-slate-400">
                      {item.completion_tokens.toLocaleString()}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-right text-slate-900 dark:text-white font-semibold">
                      {item.total_tokens.toLocaleString()}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-center">
                      {item.cache_hit_count > 0 ? (
                        <span className="text-emerald-600 dark:text-emerald-400 font-medium">
                          {item.cache_hit_count}
                        </span>
                      ) : (
                        <span className="text-slate-400">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-center">
                      {item.fallback_count > 0 ? (
                        <span className="text-amber-600 dark:text-amber-400 font-medium">
                          {item.fallback_count}
                        </span>
                      ) : (
                        <span className="text-slate-400">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-right text-emerald-600 dark:text-emerald-400 font-semibold">
                      ${item.estimated_cost_usd.toFixed(4)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
