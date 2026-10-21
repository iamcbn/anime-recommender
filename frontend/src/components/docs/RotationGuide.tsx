// frontend/src/components/docs/RotationGuide.tsx
import React from 'react';
import { RefreshCw, CheckCircle2, ShieldAlert, ArrowRight } from 'lucide-react';

export const RotationGuide: React.FC = () => {
  const steps = [
    {
      num: 1,
      title: 'Generate New Key',
      desc: 'Open the Developer Portal and generate a replacement key with a distinct name (e.g., prod-v2).',
    },
    {
      num: 2,
      title: 'Deploy to Servers',
      desc: 'Update your production environment variable (ANIME_API_KEY) with the newly generated key.',
    },
    {
      num: 3,
      title: 'Verify Inbound Traffic',
      desc: 'Confirm requests succeed and observe the new key prefix in response headers or telemetry.',
    },
    {
      num: 4,
      title: 'Revoke Old Key',
      desc: 'Return to the Developer Portal and revoke the deprecated key. Revocation is enforced globally within 60s.',
    },
  ];

  return (
    <div className="rounded-xl border border-slate-200 dark:border-dark-800 bg-white dark:bg-dark-900 p-6 flex flex-col gap-6 shadow-sm transition-colors">
      <div className="flex items-center gap-3">
        <div className="p-2.5 rounded-lg bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-brand-light">
          <RefreshCw className="w-5 h-5" />
        </div>
        <div>
          <h3 className="text-base font-semibold text-slate-900 dark:text-white">Zero-Downtime Key Rotation SOP</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Rotate compromised or expiring keys without interrupting client service.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {steps.map((step) => (
          <div
            key={step.num}
            className="p-4 rounded-xl bg-slate-50 dark:bg-dark-950 border border-slate-200 dark:border-dark-800 flex flex-col gap-2 relative shadow-xs"
          >
            <div className="w-7 h-7 rounded-full bg-brand/10 border border-brand/30 text-brand dark:bg-brand/20 dark:border-brand/40 dark:text-brand-light font-bold text-xs flex items-center justify-center">
              {step.num}
            </div>
            <h4 className="text-sm font-semibold text-slate-900 dark:text-white mt-1">{step.title}</h4>
            <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed">{step.desc}</p>
          </div>
        ))}
      </div>

      <div className="p-3.5 bg-slate-50 dark:bg-dark-950 border border-slate-200 dark:border-dark-800 rounded-lg text-xs text-slate-600 dark:text-slate-400 flex items-start gap-2.5">
        <ShieldAlert className="w-4 h-4 text-amber-500 dark:text-amber-400 shrink-0 mt-0.5" />
        <span>
          <strong className="text-slate-900 dark:text-white">Documented Revocation Lag:</strong> Once a key is soft-revoked in the Developer Portal,
          in-process backend auth caches evict the key within ≤ 60 seconds. A Redis tombstone is published
          immediately.
        </span>
      </div>
    </div>
  );
};
