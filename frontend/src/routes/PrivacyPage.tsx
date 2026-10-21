// frontend/src/routes/PrivacyPage.tsx
import React from 'react';
import { Link } from 'react-router-dom';

export const PrivacyPage: React.FC = () => {
  return (
    <div className="max-w-3xl mx-auto py-4">
      <div className="pb-6 border-b border-slate-200 dark:border-dark-800">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">
          Privacy Policy
        </h1>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
          Last updated: October 21, 2026
        </p>
      </div>

      <div className="mt-8 flex flex-col gap-8 text-xs text-slate-600 dark:text-slate-300 leading-relaxed">
        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
            1. Overview
          </h2>
          <p>
            Anime Recommender (&ldquo;we&rdquo;, &ldquo;us&rdquo;) respects your privacy. This Privacy Policy explains what information we collect when you use our Developer Portal and API, how that information is used, and the choices you have regarding your data.
          </p>
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
            2. Information We Collect
          </h2>
          <p>We collect only the information necessary to provide and secure our developer platform:</p>
          <ul className="list-disc pl-5 flex flex-col gap-1.5 text-slate-600 dark:text-slate-400">
            <li>
              <strong className="text-slate-800 dark:text-slate-200">Account Credentials:</strong> When you register via email or GitHub OAuth, we receive your email address and authentication identifiers. We do not store plaintext passwords.
            </li>
            <li>
              <strong className="text-slate-800 dark:text-slate-200">API Key Records:</strong> We store metadata about your API keys (name, prefix, creation date, and last used timestamp). Raw API keys are hashed with HMAC-SHA256 upon generation and are never saved in plaintext in our database.
            </li>
            <li>
              <strong className="text-slate-800 dark:text-slate-200">Service Telemetry:</strong> When API requests are made to our endpoints, we log request metadata including query text, response status codes, execution latency, user-agent strings, and pseudonymous client IP hashes to monitor service health and enforce rate limits. Raw client IP addresses are not permanently retained.
            </li>
          </ul>
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
            3. How We Use Information
          </h2>
          <p>We use collected data solely to:</p>
          <ul className="list-disc pl-5 flex flex-col gap-1.5 text-slate-600 dark:text-slate-400">
            <li>Authenticate API requests and issue Bearer tokens.</li>
            <li>Enforce sliding-window rate limits and prevent abuse.</li>
            <li>Monitor API latency, system errors, and retrieval quality.</li>
            <li>Notify you regarding security notices or account changes.</li>
          </ul>
          <p>We do not sell, rent, or monetize your personal data or search queries.</p>
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
            4. Third-Party Sub-processors
          </h2>
          <p>
            To deliver our service, we rely on established third-party infrastructure providers that comply with applicable data protection standards:
          </p>
          <ul className="list-disc pl-5 flex flex-col gap-1.5 text-slate-600 dark:text-slate-400">
            <li>
              <strong className="text-slate-800 dark:text-slate-200">Supabase:</strong> Authentication identity provider and relational database hosting.
            </li>
            <li>
              <strong className="text-slate-800 dark:text-slate-200">Upstash:</strong> Distributed Redis for sliding-window rate limiting and revocation tombstones.
            </li>
            <li>
              <strong className="text-slate-800 dark:text-slate-200">GitHub:</strong> Optional third-party OAuth authentication provider.
            </li>
          </ul>
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
            5. Data Retention and Security
          </h2>
          <p>
            Developer API keys automatically expire after 90 days unless rotated or revoked earlier. Telemetry and access logs are retained on a rolling basis and regularly pruned or archived to cold storage. We maintain strict role-based access control (RBAC) and row-level security (RLS) on all production data tables.
          </p>
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
            6. Your Rights
          </h2>
          <p>
            Depending on your location, you may have rights under data privacy laws (such as the Nigeria Data Protection Act (NDPA) or GDPR) to access, correct, or delete your personal data. You may revoke API keys at any time through the Developer Portal. To request account deletion or data removal, please contact the maintainers.
          </p>
        </section>

        <div className="pt-6 border-t border-slate-200 dark:border-dark-800 flex items-center justify-between">
          <Link
            to="/terms"
            className="text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white transition-colors"
          >
            &larr; Terms of Service
          </Link>
          <Link
            to="/docs"
            className="text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white transition-colors"
          >
            Back to Documentation &rarr;
          </Link>
        </div>
      </div>
    </div>
  );
};
