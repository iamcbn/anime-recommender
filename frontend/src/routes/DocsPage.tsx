// frontend/src/routes/DocsPage.tsx
import React from 'react';
import { BookOpen, Key, Terminal, AlertTriangle, ShieldCheck, Zap } from 'lucide-react';
import { CodeSnippetTabs } from '../components/docs/CodeSnippetTabs';
import { ErrorCatalog } from '../components/docs/ErrorCatalog';
import { RotationGuide } from '../components/docs/RotationGuide';

export const DocsPage: React.FC = () => {
  return (
    <div className="flex flex-col gap-10 max-w-5xl mx-auto">
      {/* Hero Section */}
      <div className="flex flex-col gap-3 pb-6 border-b border-slate-200 dark:border-dark-800">
        <div className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-brand">
          <BookOpen className="w-4 h-4" />
          Developer Documentation & Guides
        </div>
        <h1 className="text-3xl font-extrabold text-slate-900 dark:text-white tracking-tight sm:text-4xl">
          Anime Recommender API
        </h1>
        <p className="text-sm text-slate-600 dark:text-slate-300 max-w-2xl leading-relaxed">
          Integrate semantic and hybrid anime recommendations into your backend applications.
          Authenticate requests using high-entropy per-developer API keys with built-in rate limiting and telemetry.
        </p>
      </div>

      {/* Getting Started Guide */}
      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-bold text-slate-900 dark:text-white tracking-tight flex items-center gap-2">
          <Zap className="w-5 h-5 text-amber-500" />
          1. Quick Start & Onboarding
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
          <div className="p-4 rounded-xl bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-xl shadow-sm flex flex-col gap-2">
            <span className="font-mono text-indigo-600 dark:text-indigo-400 font-semibold text-sm">Step 1</span>
            <h4 className="font-semibold text-slate-900 dark:text-white">Create an Account</h4>
            <p className="text-slate-500 dark:text-slate-400 leading-relaxed">
              Sign up or log in via GitHub OAuth or magic link in the Developer Portal.
            </p>
          </div>

          <div className="p-4 rounded-xl bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-xl shadow-sm flex flex-col gap-2">
            <span className="font-mono text-indigo-600 dark:text-indigo-400 font-semibold text-sm">Step 2</span>
            <h4 className="font-semibold text-slate-900 dark:text-white">Generate an API Key</h4>
            <p className="text-slate-500 dark:text-slate-400 leading-relaxed">
              Navigate to API Keys and click &ldquo;Create API Key&rdquo;. Safely copy your raw key.
            </p>
          </div>

          <div className="p-4 rounded-xl bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-xl shadow-sm flex flex-col gap-2">
            <span className="font-mono text-indigo-600 dark:text-indigo-400 font-semibold text-sm">Step 3</span>
            <h4 className="font-semibold text-slate-900 dark:text-white">Call the API</h4>
            <p className="text-slate-500 dark:text-slate-400 leading-relaxed">
              Include <code className="bg-slate-100 dark:bg-dark-950 px-1 py-0.5 rounded text-indigo-700 dark:text-indigo-300">Authorization: Bearer &lt;key&gt;</code> in your backend requests.
            </p>
          </div>
        </div>
      </section>

      {/* Security Best Practices */}
      <div className="p-4 rounded-xl bg-amber-50 border border-amber-200 text-amber-800 dark:bg-amber-500/10 dark:border-amber-500/30 dark:text-amber-300 text-xs flex items-start gap-3">
        <AlertTriangle className="w-5 h-5 text-amber-500 dark:text-amber-400 shrink-0 mt-0.5" />
        <div className="flex flex-col gap-1">
          <span className="font-semibold text-amber-900 dark:text-amber-200">Security Warning: Keep Your API Key Secret</span>
          <p className="leading-relaxed">
            API keys must only be stored in secure backend environment variables (e.g.{' '}
            <code className="bg-amber-100 dark:bg-amber-500/20 px-1 py-0.5 rounded">ANIME_API_KEY</code>). Never commit
            keys to version control, and <strong>never expose them in frontend client-side JavaScript or mobile apps</strong>.
          </p>
        </div>
      </div>

      {/* Code Snippets Section */}
      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-bold text-slate-900 dark:text-white tracking-tight flex items-center gap-2">
          <Terminal className="w-5 h-5 text-brand" />
          2. Code Examples
        </h2>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Select your programming language to view authenticated request examples for <code className="text-indigo-600 dark:text-indigo-400 font-mono">POST /recommend</code>:
        </p>
        <CodeSnippetTabs />
      </section>

      {/* API Endpoints Summary */}
      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-bold text-slate-900 dark:text-white tracking-tight flex items-center gap-2">
          <Key className="w-5 h-5 text-emerald-500 dark:text-emerald-400" />
          3. API Endpoints
        </h2>
        <div className="rounded-xl border border-slate-200 dark:border-dark-800 bg-white dark:bg-dark-900 divide-y divide-slate-200 dark:divide-dark-800 overflow-hidden text-xs shadow-sm">
          <div className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div>
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded bg-indigo-50 dark:bg-indigo-500/10 text-indigo-700 dark:text-indigo-400 font-mono font-bold">
                  POST
                </span>
                <span className="font-mono text-slate-900 dark:text-white font-semibold">/recommend</span>
              </div>
              <p className="text-slate-500 dark:text-slate-400 mt-1">
                Returns clean anime recommendation cards. Stripped of internal model scores and timings.
              </p>
            </div>
            <span className="text-slate-400 dark:text-slate-500 font-mono">Auth: Bearer Key</span>
          </div>

          <div className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div>
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 font-mono font-bold">
                  POST
                </span>
                <span className="font-mono text-slate-900 dark:text-white font-semibold">/chat</span>
              </div>
              <p className="text-slate-500 dark:text-slate-400 mt-1">
                Conversational RAG streaming response with guardrail confidence filters.
              </p>
            </div>
            <span className="text-slate-400 dark:text-slate-500 font-mono">Auth: Bearer Key</span>
          </div>

          <div className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div>
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 font-mono font-bold">
                  POST
                </span>
                <span className="font-mono text-slate-900 dark:text-white font-semibold">/admin/recommend</span>
              </div>
              <p className="text-slate-500 dark:text-slate-400 mt-1">
                Admin evaluation endpoint returning full timings, RRF scores, and cross-encoder scores.
              </p>
            </div>
            <span className="text-slate-400 dark:text-slate-500 font-mono">Auth: Admin Role Key</span>
          </div>
        </div>
      </section>

      {/* Error Reference Catalog */}
      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-bold text-slate-900 dark:text-white tracking-tight flex items-center gap-2">
          <ShieldCheck className="w-5 h-5 text-indigo-500 dark:text-indigo-400" />
          4. Error Codes & Troubleshooting
        </h2>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          All API errors return uniform error envelopes: <code className="text-indigo-600 dark:text-indigo-400 font-mono">{`{"error": {"code": "...", "message": "..."}}`}</code>.
        </p>
        <ErrorCatalog />
      </section>

      {/* Rotation SOP */}
      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-bold text-slate-900 dark:text-white tracking-tight flex items-center gap-2">
          <Key className="w-5 h-5 text-brand" />
          5. Key Rotation Guide
        </h2>
        <RotationGuide />
      </section>
    </div>
  );
};
