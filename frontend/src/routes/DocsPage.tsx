// frontend/src/routes/DocsPage.tsx
import React from 'react';
import { Link } from 'react-router-dom';
import { CodeBlock } from '../components/common/CodeBlock';
import { CodeSnippetTabs } from '../components/docs/CodeSnippetTabs';
import { ErrorCatalog } from '../components/docs/ErrorCatalog';
import { RotationGuide } from '../components/docs/RotationGuide';

const sampleResponseJson = `{
  "query": "psychological mystery with suspenseful plot twists",
  "count": 1,
  "allowed_adult": false,
  "results": [
    {
      "id": 19,
      "title_romaji": "Monster",
      "title_userPreferred": "Monster",
      "title_english": "Monster",
      "coverImage_large": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/medium/bx19-ham53gnijfiN.jpg",
      "description": "Dr. Kenzou Tenma is a renowned brain surgeon in Germany...",
      "genres": ["Drama", "Mystery", "Psychological", "Thriller"],
      "studios": ["Madhouse"],
      "tags": ["Crime", "Detective", "Fugitive", "Medicine", "Noir"],
      "averageScore": 88,
      "seasonYear": 2004,
      "episodes": 74,
      "status": "FINISHED"
    }
  ]
}`;

export const DocsPage: React.FC = () => {
  return (
    <div className="max-w-6xl mx-auto flex flex-col lg:flex-row gap-10">
      {/* Left Sidebar Navigation */}
      <aside className="lg:w-52 shrink-0">
        <div className="lg:sticky lg:top-24 flex flex-col gap-1 text-xs">
          <span className="font-semibold text-slate-900 dark:text-white px-2.5 py-1.5">
            API Reference
          </span>
          <a
            href="#authentication"
            className="px-2.5 py-1.5 rounded text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-dark-900 transition-colors"
          >
            Authentication
          </a>
          <a
            href="#post-recommend"
            className="px-2.5 py-1.5 rounded text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-dark-900 transition-colors"
          >
            POST /recommend
          </a>
          <a
            href="#code-examples"
            className="px-2.5 py-1.5 rounded text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-dark-900 transition-colors"
          >
            Code Examples
          </a>
          <a
            href="#errors"
            className="px-2.5 py-1.5 rounded text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-dark-900 transition-colors"
          >
            Errors
          </a>
          <a
            href="#key-rotation"
            className="px-2.5 py-1.5 rounded text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-dark-900 transition-colors"
          >
            Key Rotation
          </a>
        </div>
      </aside>

      {/* Main Content Column */}
      <div className="flex-1 min-w-0 flex flex-col gap-12">
        {/* Page Header */}
        <div className="pb-6 border-b border-slate-200 dark:border-dark-800">
          <h1 className="text-2xl sm:text-3xl font-bold text-slate-900 dark:text-white tracking-tight">
            Anime Recommender API
          </h1>
          <p className="text-sm text-slate-600 dark:text-slate-300 mt-2 max-w-2xl leading-relaxed">
            Query anime recommendations using natural-language descriptions, moods, or genre prompts.
            Responses are returned in JSON format with title metadata, synopses, studios, and cover images.
          </p>
        </div>

        {/* Authentication */}
        <section id="authentication" className="flex flex-col gap-3 scroll-mt-20">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white tracking-tight">
            Authentication
          </h2>
          <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed">
            Generate an API key in the{' '}
            <Link to="/developers" className="underline font-medium text-slate-900 dark:text-white">
              API Keys
            </Link>{' '}
            tab and pass it in the <code className="font-mono bg-slate-100 dark:bg-dark-900 px-1.5 py-0.5 rounded">Authorization</code> header of your server-side requests:
          </p>
          <div className="p-3 rounded-lg bg-slate-900 dark:bg-dark-900 border border-slate-800 dark:border-dark-800 font-mono text-xs text-slate-200">
            Authorization: Bearer ar_live_...
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
            Keep your API key in a backend environment variable (such as <code className="font-mono">ANIME_API_KEY</code>). Do not embed keys in browser JavaScript or mobile clients. Each key is rate-limited to 20 requests per minute.
          </p>
        </section>

        {/* Endpoint Reference: POST /recommend */}
        <section id="post-recommend" className="flex flex-col gap-5 scroll-mt-20">
          <div className="flex flex-col gap-2">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white tracking-tight">
              Endpoint
            </h2>
            <div className="inline-flex items-center gap-2.5 self-start px-3 py-1.5 rounded-md bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800">
              <span className="px-2 py-0.5 rounded bg-slate-900 dark:bg-white text-white dark:text-slate-950 font-mono text-xs font-bold">
                POST
              </span>
              <span className="font-mono text-sm font-semibold text-slate-900 dark:text-white">
                /recommend
              </span>
            </div>
            <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed mt-1">
              Returns a JSON object containing ranked anime recommendations matching the provided query.
            </p>
          </div>

          {/* Request Body Parameters */}
          <div className="flex flex-col gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Request Body (application/json)
            </h3>
            <div className="rounded-lg border border-slate-200 dark:border-dark-800 bg-white dark:bg-dark-900 overflow-hidden">
              <table className="w-full text-left text-xs text-slate-700 dark:text-slate-300">
                <thead className="bg-slate-50 dark:bg-dark-950 font-medium text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-dark-800">
                  <tr>
                    <th className="px-4 py-2.5">Parameter</th>
                    <th className="px-4 py-2.5">Type</th>
                    <th className="px-4 py-2.5">Required</th>
                    <th className="px-4 py-2.5">Default</th>
                    <th className="px-4 py-2.5">Description</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 dark:divide-dark-800">
                  <tr>
                    <td className="px-4 py-3 font-mono font-medium text-slate-900 dark:text-white">query</td>
                    <td className="px-4 py-3 font-mono text-slate-500">string</td>
                    <td className="px-4 py-3">Yes</td>
                    <td className="px-4 py-3 font-mono text-slate-400">—</td>
                    <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                      Natural-language prompt describing the anime, mood, or plot (minimum 2 characters).
                    </td>
                  </tr>
                  <tr>
                    <td className="px-4 py-3 font-mono font-medium text-slate-900 dark:text-white">top_k</td>
                    <td className="px-4 py-3 font-mono text-slate-500">integer</td>
                    <td className="px-4 py-3">No</td>
                    <td className="px-4 py-3 font-mono">20</td>
                    <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                      Maximum number of recommendations to return.
                    </td>
                  </tr>
                  <tr>
                    <td className="px-4 py-3 font-mono font-medium text-slate-900 dark:text-white">allow_adult</td>
                    <td className="px-4 py-3 font-mono text-slate-500">boolean</td>
                    <td className="px-4 py-3">No</td>
                    <td className="px-4 py-3 font-mono">false</td>
                    <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                      Whether to include 18+ adult entries in the returned list.
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          {/* Response Format */}
          <div className="flex flex-col gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Response Format (200 OK)
            </h3>
            <p className="text-xs text-slate-600 dark:text-slate-400">
              Returns a JSON object with the original <code className="font-mono">query</code>, result <code className="font-mono">count</code>, <code className="font-mono">allowed_adult</code> flag, and the <code className="font-mono">results</code> array:
            </p>
            <CodeBlock code={sampleResponseJson} language="json" filename="200 OK — application/json" />
          </div>
        </section>

        {/* Code Snippets Section */}
        <section id="code-examples" className="flex flex-col gap-3 scroll-mt-20">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white tracking-tight">
            Code Examples
          </h2>
          <CodeSnippetTabs />
        </section>

        {/* Error Reference Catalog */}
        <section id="errors" className="flex flex-col gap-3 scroll-mt-20">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white tracking-tight">
            Errors
          </h2>
          <p className="text-xs text-slate-600 dark:text-slate-400">
            Failed requests return a structured JSON error payload: <code className="font-mono">{`{"error": {"code": "...", "message": "..."}}`}</code>.
          </p>
          <ErrorCatalog />
        </section>

        {/* Key Rotation */}
        <section id="key-rotation" className="flex flex-col gap-3 scroll-mt-20">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white tracking-tight">
            Key Rotation
          </h2>
          <RotationGuide />
        </section>
      </div>
    </div>
  );
};
