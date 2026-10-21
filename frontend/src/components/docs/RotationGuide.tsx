// frontend/src/components/docs/RotationGuide.tsx
import React from 'react';

export const RotationGuide: React.FC = () => {
  const steps = [
    {
      num: 1,
      title: 'Generate New Key',
      desc: 'Create a replacement key in the API Keys tab with a distinct name (for example, prod-2026-10).',
    },
    {
      num: 2,
      title: 'Deploy to Servers',
      desc: 'Update your ANIME_API_KEY environment variable in production and redeploy your backend.',
    },
    {
      num: 3,
      title: 'Verify Inbound Traffic',
      desc: 'Check the Last Used column in the API Keys table to confirm your servers are using the new key.',
    },
    {
      num: 4,
      title: 'Revoke Old Key',
      desc: 'Revoke the previous key. Revoked keys stop working across all workers within 60 seconds.',
    },
  ];

  return (
    <div className="rounded-lg border border-slate-200 dark:border-dark-800 bg-white dark:bg-dark-900 divide-y divide-slate-200 dark:divide-dark-800 text-xs">
      {steps.map((step) => (
        <div key={step.num} className="p-4 flex items-baseline gap-3">
          <span className="font-mono font-semibold text-slate-400 dark:text-slate-500 shrink-0">
            0{step.num}
          </span>
          <div>
            <span className="font-semibold text-slate-900 dark:text-white">{step.title}</span>
            <span className="text-slate-600 dark:text-slate-400 ml-2">{step.desc}</span>
          </div>
        </div>
      ))}
    </div>
  );
};
