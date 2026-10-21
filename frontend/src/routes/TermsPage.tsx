// frontend/src/routes/TermsPage.tsx
import React from 'react';
import { Link } from 'react-router-dom';

export const TermsPage: React.FC = () => {
  return (
    <div className="max-w-3xl mx-auto py-4">
      <div className="pb-6 border-b border-slate-200 dark:border-dark-800">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">
          Terms of Service
        </h1>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
          Last updated: October 21, 2026
        </p>
      </div>

      <div className="mt-8 flex flex-col gap-8 text-xs text-slate-600 dark:text-slate-300 leading-relaxed">
        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
            1. Acceptance of Terms
          </h2>
          <p>
            By creating an account, generating an API key, or accessing the Anime Recommender API (&ldquo;Service&rdquo;), you agree to be bound by these Terms of Service. If you do not agree to these terms, do not access or use the Service.
          </p>
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
            2. API Keys and Authentication
          </h2>
          <p>
            You must register for an account to generate API keys. You are responsible for safeguarding your credentials and API keys. You agree not to disclose your secret API keys to any third party or embed them in client-side code (such as web browsers or mobile applications). You accept responsibility for all requests originating from your API keys.
          </p>
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
            3. Acceptable Use Policy
          </h2>
          <p>You agree not to use the Service to:</p>
          <ul className="list-disc pl-5 flex flex-col gap-1.5 text-slate-600 dark:text-slate-400">
            <li>Bypass, disable, or circumvent API rate limits, authentication barriers, or quotas.</li>
            <li>Conduct automated denial-of-service attacks, credential stuffing, or excessive queries that degrade service availability.</li>
            <li>Reverse-engineer, decompile, or extract the underlying model weights or proprietary algorithms.</li>
            <li>Resell, lease, or sublicense raw access to the API without prior written consent.</li>
            <li>Use the service in violation of any applicable local, national, or international laws.</li>
          </ul>
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
            4. Rate Limits and Quotas
          </h2>
          <p>
            API access is subject to usage throttles (currently 20 requests per minute per key, and a maximum of 5 active keys per developer account). If you exceed these limits, requests will return HTTP 429 (Too Many Requests). We reserve the right to modify rate limits or quotas at any time to preserve platform stability.
          </p>
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
            5. Termination and Revocation
          </h2>
          <p>
            We reserve the right to suspend, revoke, or terminate your API keys or developer account at any time, with or without notice, if we reasonably determine that your usage violates these terms or poses a security or performance risk to our systems or other users.
          </p>
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
            6. Disclaimers and Limitation of Liability
          </h2>
          <p>
            The Service and recommendations are provided strictly on an &ldquo;as-is&rdquo; and &ldquo;as-available&rdquo; basis without warranties of any kind, whether express or implied. We do not guarantee uninterrupted availability, accuracy of recommendations, or specific performance outcomes.
          </p>
          <p>
            To the maximum extent permitted by applicable law, Anime Recommender and its maintainers shall not be liable for any indirect, incidental, special, consequential, or punitive damages, or any loss of profits or revenues, resulting from your use of or inability to use the Service.
          </p>
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
            7. Changes to These Terms
          </h2>
          <p>
            We may update these Terms of Service from time to time. Updated versions will be posted on this page with an updated revision date. Continued use of the Service following any revisions constitutes your acceptance of the revised terms.
          </p>
        </section>

        <div className="pt-6 border-t border-slate-200 dark:border-dark-800 flex items-center justify-between">
          <Link
            to="/docs"
            className="text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white transition-colors"
          >
            &larr; Back to Documentation
          </Link>
          <Link
            to="/privacy"
            className="text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white transition-colors"
          >
            Privacy Policy &rarr;
          </Link>
        </div>
      </div>
    </div>
  );
};
