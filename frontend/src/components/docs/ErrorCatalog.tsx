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
      code: 'unauthorized',
      description: 'The Authorization header is missing, malformed, or the API key is invalid, expired, or revoked.',
      resolution: 'Verify your key format (ar_live_<prefix>_<secret>) and pass it as Authorization: Bearer <key>.',
    },
    {
      status: 403,
      code: 'forbidden',
      description: 'The API key does not have permission to call this endpoint.',
      resolution: 'Ensure your key is active and requests are sent to POST /recommend.',
    },
    {
      status: 404,
      code: 'key_not_found',
      description: 'The requested API key ID does not exist under your developer account.',
      resolution: 'Check the key ID in the API Keys tab.',
    },
    {
      status: 409,
      code: 'key_limit_reached / duplicate_key_name',
      description: 'Your account already has 5 active keys, or an active key with the same name already exists.',
      resolution: 'Revoke an unused key or choose a different key name.',
    },
    {
      status: 422,
      code: 'validation_error',
      description: 'The request body failed validation (for example, query is shorter than 2 characters).',
      resolution: 'Check the request parameters table for POST /recommend.',
    },
    {
      status: 429,
      code: 'rate_limit_exceeded',
      description: 'The per-key rate limit (20 requests/minute) has been exceeded.',
      resolution: 'Read the Retry-After response header and wait before retrying.',
    },
  ];

  return (
    <div className="rounded-lg border border-slate-200 dark:border-dark-800 bg-white dark:bg-dark-900 overflow-hidden transition-colors">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs text-slate-700 dark:text-slate-300">
          <thead className="bg-slate-50 dark:bg-dark-950 font-medium text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-dark-800">
            <tr>
              <th className="px-4 py-2.5">Status</th>
              <th className="px-4 py-2.5">Code</th>
              <th className="px-4 py-2.5">Description</th>
              <th className="px-4 py-2.5">Resolution</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 dark:divide-dark-800">
            {errorList.map((err, i) => (
              <tr key={i} className="hover:bg-slate-50 dark:hover:bg-dark-800/40 transition-colors">
                <td className="px-4 py-3 font-mono">
                  <Badge
                    variant={err.status >= 500 ? 'danger' : err.status === 429 ? 'warning' : 'neutral'}
                    size="sm"
                  >
                    {err.status}
                  </Badge>
                </td>
                <td className="px-4 py-3 font-mono text-slate-900 dark:text-white font-medium">
                  {err.code}
                </td>
                <td className="px-4 py-3 text-slate-600 dark:text-slate-300 max-w-xs">{err.description}</td>
                <td className="px-4 py-3 text-slate-500 dark:text-slate-400 max-w-xs">{err.resolution}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
