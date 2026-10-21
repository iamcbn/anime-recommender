// frontend/src/components/admin/LogDetailModal.tsx
import React from 'react';
import { Copy, Check, Clock, BarChart2 } from 'lucide-react';
import { Modal } from '../common/Modal';
import { Badge } from '../common/Badge';
import { CodeBlock } from '../common/CodeBlock';
import { useClipboard } from '../../hooks/useClipboard';
import type { RecommendationLog } from '../../types/telemetry';

export interface LogDetailModalProps {
  log: RecommendationLog | null;
  isOpen: boolean;
  onClose: () => void;
}

export const LogDetailModal: React.FC<LogDetailModalProps> = ({ log, isOpen, onClose }) => {
  const { copied, copy } = useClipboard();

  if (!log) return null;

  const rawJson = JSON.stringify(log, null, 2);

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={`Telemetry Event #${log.id}`}
      description={`Request ID: ${log.request_id}`}
      maxWidth="2xl"
    >
      <div className="flex flex-col gap-4 max-h-[70vh] overflow-y-auto pr-1">
        {/* Quick Meta Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-xs">
          <div className="p-2.5 rounded-lg bg-slate-50 dark:bg-dark-950 border border-slate-200 dark:border-dark-800">
            <span className="text-slate-500 dark:text-slate-400 block mb-0.5">Endpoint</span>
            <span className="font-mono text-indigo-600 dark:text-indigo-400 font-semibold">{log.endpoint}</span>
          </div>

          <div className="p-2.5 rounded-lg bg-slate-50 dark:bg-dark-950 border border-slate-200 dark:border-dark-800">
            <span className="text-slate-500 dark:text-slate-400 block mb-0.5">Source</span>
            <Badge variant={log.source === 'admin_eval' ? 'brand' : 'neutral'} size="sm">
              {log.source}
            </Badge>
          </div>

          <div className="p-2.5 rounded-lg bg-slate-50 dark:bg-dark-950 border border-slate-200 dark:border-dark-800">
            <span className="text-slate-500 dark:text-slate-400 block mb-0.5">Total Latency</span>
            <span className="font-mono text-emerald-600 dark:text-emerald-400 font-semibold">
              {log.total_ms ? `${log.total_ms.toFixed(1)} ms` : 'N/A'}
            </span>
          </div>

          <div className="p-2.5 rounded-lg bg-slate-50 dark:bg-dark-950 border border-slate-200 dark:border-dark-800">
            <span className="text-slate-500 dark:text-slate-400 block mb-0.5">Results Count</span>
            <span className="font-mono text-slate-700 dark:text-slate-200 font-semibold">
              {log.results_count} / {log.top_k}
            </span>
          </div>
        </div>

        {/* Query Content */}
        <div className="p-3 rounded-lg bg-slate-50 dark:bg-dark-950 border border-slate-200 dark:border-dark-800 text-xs">
          <span className="text-slate-500 dark:text-slate-400 block mb-1 font-medium">User / Eval Query:</span>
          <p className="text-slate-800 dark:text-slate-200 font-mono italic break-words">&ldquo;{log.query}&rdquo;</p>
        </div>

        {/* Error banner if present */}
        {log.error && (
          <div className="p-3 rounded-lg bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-xs text-red-700 dark:text-red-300">
            <span className="font-semibold block mb-0.5">Execution Error:</span>
            <p className="font-mono">{log.error}</p>
          </div>
        )}

        {/* Timings Breakdown */}
        {log.timings && Object.keys(log.timings).length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-slate-700 dark:text-slate-300 mb-2 flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5 text-indigo-500 dark:text-indigo-400" />
              Pipeline Timings Breakdown
            </h4>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
              {Object.entries(log.timings).map(([key, val]) => (
                <div key={key} className="p-2 bg-slate-50 dark:bg-dark-950 border border-slate-200 dark:border-dark-800 rounded">
                  <span className="text-slate-500 dark:text-slate-400 block text-[10px] truncate">{key}</span>
                  <span className="font-mono text-slate-800 dark:text-slate-200 font-medium">
                    {typeof val === 'number' ? `${val.toFixed(2)} ms` : String(val)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Candidate Scores Sample */}
        {log.candidate_scores && log.candidate_scores.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-slate-700 dark:text-slate-300 mb-2 flex items-center gap-1.5">
              <BarChart2 className="w-3.5 h-3.5 text-emerald-500 dark:text-emerald-400" />
              Candidate Scores (Top Candidates)
            </h4>
            <div className="space-y-1.5">
              {log.candidate_scores.slice(0, 5).map((scoreItem, idx) => (
                <div
                  key={idx}
                  className="flex items-center justify-between p-2 rounded bg-slate-50 dark:bg-dark-950 border border-slate-200 dark:border-dark-800 text-xs font-mono"
                >
                  <span className="text-slate-600 dark:text-slate-400">Anime #{scoreItem.id}</span>
                  <div className="flex items-center gap-3 text-slate-700 dark:text-slate-300">
                    {scoreItem.cross_encoder_score !== undefined && (
                      <span>CE: {scoreItem.cross_encoder_score.toFixed(3)}</span>
                    )}
                    {scoreItem.final_rrf_score !== undefined && (
                      <span className="text-emerald-600 dark:text-emerald-400">RRF: {scoreItem.final_rrf_score.toFixed(4)}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Full Raw JSON */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-semibold text-slate-700 dark:text-slate-300">Raw Telemetry JSON</span>
            <button
              onClick={() => copy(rawJson)}
              className="text-xs text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white flex items-center gap-1 transition-colors"
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-emerald-500 dark:text-emerald-400" />
                  <span className="text-emerald-600 dark:text-emerald-400">Copied</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5" />
                  <span>Copy JSON</span>
                </>
              )}
            </button>
          </div>
          <CodeBlock code={rawJson} language="json" />
        </div>
      </div>
    </Modal>
  );
};
