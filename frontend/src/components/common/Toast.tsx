// frontend/src/components/common/Toast.tsx
import React from 'react';
import { CheckCircle2, AlertTriangle, AlertCircle, Info, X } from 'lucide-react';

export interface ToastProps {
  id: string;
  type?: 'success' | 'warning' | 'error' | 'info';
  title?: string;
  message: string;
  onDismiss: (id: string) => void;
}

export const Toast: React.FC<ToastProps> = ({
  id,
  type = 'info',
  title,
  message,
  onDismiss,
}) => {
  const iconMap = {
    success: <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />,
    warning: <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0" />,
    error: <AlertCircle className="w-5 h-5 text-red-400 shrink-0" />,
    info: <Info className="w-5 h-5 text-sky-400 shrink-0" />,
  };

  const borderStyles = {
    success: 'border-emerald-500/30 bg-emerald-950/40',
    warning: 'border-amber-500/30 bg-amber-950/40',
    error: 'border-red-500/30 bg-red-950/40',
    info: 'border-sky-500/30 bg-sky-950/40',
  };

  return (
    <div
      className={`flex items-start gap-3 p-4 rounded-xl border ${borderStyles[type]} shadow-xl text-sm max-w-sm w-full backdrop-blur-md transition-all animate-slide-in`}
    >
      {iconMap[type]}
      <div className="flex-1 min-w-0">
        {title && <h4 className="font-semibold text-white">{title}</h4>}
        <p className="text-slate-300 break-words">{message}</p>
      </div>
      <button
        onClick={() => onDismiss(id)}
        className="text-slate-400 hover:text-white transition-colors"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
};
