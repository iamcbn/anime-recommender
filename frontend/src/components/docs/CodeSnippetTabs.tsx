// frontend/src/components/docs/CodeSnippetTabs.tsx
import React, { useState } from 'react';
import { CodeBlock } from '../common/CodeBlock';

export const CodeSnippetTabs: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'curl' | 'python' | 'js'>('curl');

  const curlSnippet = `# Call recommendation endpoint with your Bearer API key
curl -X POST "https://api.anime-recommender.com/recommend" \\
  -H "Authorization: Bearer $ANIME_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "query": "psychological mystery with suspenseful plot twists",
    "top_k": 5
  }'`;

  const pythonSnippet = `import os
import requests

# Load key securely from server environment (never hardcode in source)
API_KEY = os.environ.get("ANIME_API_KEY")
API_BASE_URL = os.environ.get("ANIME_API_BASE_URL", "https://api.anime-recommender.com")

def get_recommendations(query: str, top_k: int = 5):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "query": query,
        "top_k": top_k,
    }

    response = requests.post(f"{API_BASE_URL}/recommend", headers=headers, json=payload)
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "60")
        print(f"Rate limited. Retry after {retry_after}s")
        return None

    response.raise_for_status()
    return response.json()

if __name__ == "__main__":
    results = get_recommendations("cyberpunk detective investigating AI")
    print(results)`;

  const jsSnippet = `// Node.js / Server-side TypeScript Example
// IMPORTANT: Do NOT run this code in browser client bundles!

const API_KEY = process.env.ANIME_API_KEY;
const API_BASE_URL = process.env.ANIME_API_BASE_URL || "https://api.anime-recommender.com";

async function fetchRecommendations(query, topK = 5) {
  const res = await fetch(\`\${API_BASE_URL}/recommend\`, {
    method: "POST",
    headers: {
      "Authorization": \`Bearer \${API_KEY}\`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      query,
      top_k: topK,
    }),
  });

  if (res.status === 429) {
    const retryAfter = res.headers.get("Retry-After");
    throw new Error(\`Rate limit exceeded. Retry after \${retryAfter}s\`);
  }

  if (!res.ok) {
    const errorBody = await res.json();
    throw new Error(\`API error: \${errorBody.error?.message || res.statusText}\`);
  }

  return res.json();
}

fetchRecommendations("dark fantasy with intricate magic system")
  .then((data) => console.log("Recommended Anime:", data))
  .catch((err) => console.error(err));`;

  return (
    <div className="rounded-lg border border-slate-200 dark:border-dark-800 bg-white dark:bg-dark-900 overflow-hidden transition-colors">
      <div className="flex items-center gap-1 p-1.5 bg-slate-50 dark:bg-dark-950 border-b border-slate-200 dark:border-dark-800">
        <button
          onClick={() => setActiveTab('curl')}
          className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
            activeTab === 'curl'
              ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-950'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-200/50 dark:text-slate-400 dark:hover:text-white dark:hover:bg-dark-800'
          }`}
        >
          cURL
        </button>
        <button
          onClick={() => setActiveTab('python')}
          className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
            activeTab === 'python'
              ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-950'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-200/50 dark:text-slate-400 dark:hover:text-white dark:hover:bg-dark-800'
          }`}
        >
          Python
        </button>
        <button
          onClick={() => setActiveTab('js')}
          className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
            activeTab === 'js'
              ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-950'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-200/50 dark:text-slate-400 dark:hover:text-white dark:hover:bg-dark-800'
          }`}
        >
          Node.js
        </button>
      </div>

      <div className="p-3">
        {activeTab === 'curl' && (
          <CodeBlock code={curlSnippet} language="bash" filename="terminal" />
        )}
        {activeTab === 'python' && (
          <CodeBlock code={pythonSnippet} language="python" filename="client.py" />
        )}
        {activeTab === 'js' && (
          <CodeBlock code={jsSnippet} language="typescript" filename="client.ts" />
        )}
      </div>
    </div>
  );
};
