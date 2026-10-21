// frontend/src/components/docs/ErrorCatalog.tsx
import React from 'react';
import { Badge } from '../common/Badge';

export interface ErrorDocItem {
  status: number;
  code: string;
  description: string;
  resolution: string;
}

export const ErrorCatalog: React.FC = () => {
  const errorList: ErrorDocItem[] = [
    {
      status: 401,
      code: 'missing_token / invalid_key',
      description: 'The Authorization Bearer header is missing, malformed, or the key was not found.',
      resolution: 'Verify your API key format (ar_live_<prefix>_<secret>) and ensure it is passed via Bearer auth.',
    },
    {
      status: 401,
      code: 'revoked_key / expired_key',
      description: 'The API key has been revoked by the owner or has passed its 90-day expiry date.',
      resolution: 'Log into the Developer Portal and generate a replacement key.',
    },
    {
      status: 401,
      code: 'stale_token',
      description: 'Your Supabase Auth session token is older than 15 minutes when calling /dev/keys.',
      resolution: 'Refresh your Supabase session before issuing administrative or key generation requests.',
    },
    {
      status: 403,
      code: 'insufficient_role',
      description: 'The API key or JWT does not possess the required role (e.g. attempting to access /admin/recommend).',
      resolution: 'Use a designated admin API key or log in with an administrator account.',
    },
    {
      status: 404,
      code: 'key_not_found',
      description: 'The requested API key ID does not exist or belongs to another developer.',
      resolution: 'Verify the key UUID in the Developer Portal.',
    },
    {
      status: 409,
      code: 'key_limit_reached',
      description: 'The developer has reached the maximum quota of 5 active API keys.',
      resolution: 'Revoke an inactive or redundant key before generating a new one.',
    },
    {
      status: 409,
      code: 'duplicate_key_name',
      description: 'An active API key with the identical name already exists under your account.',
      resolution: 'Provide a distinct descriptive name for the new key.',
    },
    {
      status: 422,
      code: 'validation_error',
      description: 'The request body failed schema validation (e.g. empty query, forbidden extra fields).',
      resolution: 'Inspect the error details and ensure the payload matches the OpenAPI schema.',
    },
    {
      status: 429,
      code: 'rate_limit_exceeded',
      description: 'The per-key rate limit (default 20 requests/minute) has been exceeded.',
      resolution: 'Inspect the Retry-After response header and throttle outgoing requests.',
    },
  ];

  return (
    <div className="rounded-xl border border-slate-200 dark:border-dark-800 bg-white dark:bg-dark-900 overflow-hidden shadow-sm transition-colors">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm text-slate-700 dark:text-slate-300">
          <thead className="bg-slate-50 dark:bg-dark-950 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider border-b border-slate-200 dark:border-dark-800">
            <tr>
              <th className="px-5 py-3.5">HTTP Status</th>
              <th className="px-5 py-3.5">Error Code</th>
              <th className="px-5 py-3.5">Description</th>
              <th className="px-5 py-3.5">Resolution</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 dark:divide-dark-800 text-xs">
            {errorList.map((err, i) => (
              <tr key={i} className="hover:bg-slate-50 dark:hover:bg-dark-800/40 transition-colors">
                <td className="px-5 py-3.5 font-mono">
                  <Badge
                    variant={err.status >= 500 ? 'danger' : err.status === 429 ? 'warning' : 'neutral'}
                    size="sm"
                  >
                    {err.status}
                  </Badge>
                </td>
                <td className="px-5 py-3.5 font-mono text-indigo-600 dark:text-indigo-400 font-medium">
                  {err.code}
                </td>
                <td className="px-5 py-3.5 text-slate-700 dark:text-slate-300 max-w-xs">{err.description}</td>
                <td className="px-5 py-3.5 text-slate-500 dark:text-slate-400 max-w-xs">{err.resolution}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
