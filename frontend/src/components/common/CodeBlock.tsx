// frontend/src/components/common/CodeBlock.tsx
import React from 'react';
import { Copy, Check } from 'lucide-react';
import { useClipboard } from '../../hooks/useClipboard';

export interface CodeBlockProps {
  code: string;
  language?: string;
  filename?: string;
}

export const CodeBlock: React.FC<CodeBlockProps> = ({ code, language, filename }) => {
  const { copied, copy } = useClipboard();

  return (
    <div className="relative rounded-lg border border-dark-700 bg-dark-950 overflow-hidden text-xs my-2">
      <div className="flex items-center justify-between px-3 py-1.5 bg-dark-900 border-b border-dark-700 text-slate-400">
        <span className="font-mono text-slate-300">{filename || language || 'code'}</span>
        <button
          onClick={() => copy(code)}
          className="inline-flex items-center gap-1 text-slate-400 hover:text-white transition-colors py-0.5 px-1.5 rounded hover:bg-dark-800"
          title="Copy code"
        >
          {copied ? (
            <>
              <Check className="w-3.5 h-3.5 text-emerald-400" />
              <span className="text-emerald-400">Copied!</span>
            </>
          ) : (
            <>
              <Copy className="w-3.5 h-3.5" />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>
      <div className="p-3 overflow-x-auto">
        <pre className="font-mono text-slate-200 leading-relaxed whitespace-pre">
          <code>{code}</code>
        </pre>
      </div>
    </div>
  );
};
