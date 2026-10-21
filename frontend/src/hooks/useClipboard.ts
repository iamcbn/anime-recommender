// frontend/src/hooks/useClipboard.ts
import { useState, useCallback } from 'react';

export const useClipboard = (timeoutMs = 2000) => {
  const [copied, setCopied] = useState<boolean>(false);

  const copy = useCallback(
    async (text: string): Promise<boolean> => {
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(text);
        } else {
          // Fallback for non-secure contexts
          const textarea = document.createElement('textarea');
          textarea.value = text;
          textarea.style.position = 'fixed';
          textarea.style.opacity = '0';
          document.body.appendChild(textarea);
          textarea.select();
          document.execCommand('copy');
          document.body.removeChild(textarea);
        }
        setCopied(true);
        setTimeout(() => setCopied(false), timeoutMs);
        return true;
      } catch (err) {
        console.error('Failed to copy to clipboard:', err);
        return false;
      }
    },
    [timeoutMs]
  );

  return { copied, copy };
};
