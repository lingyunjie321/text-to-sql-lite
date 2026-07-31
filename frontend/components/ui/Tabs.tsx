"use client";

import { useState, useCallback } from "react";

interface TabsProps {
  tabs: {
    label: string;
    icon?: React.ReactNode;
    disabled?: boolean;
    disabledReason?: string;
  }[];
  activeIndex: number;
  onChange: (index: number) => void;
}

export function Tabs({ tabs, activeIndex, onChange }: TabsProps) {
  return (
    <div className="flex items-center gap-1 border-b border-[var(--color-border)]">
      {tabs.map((tab, i) => {
        const isActive = i === activeIndex;
        const isDisabled = tab.disabled;
        return (
          <button
            key={i}
            onClick={() => !isDisabled && onChange(i)}
            disabled={isDisabled}
            title={isDisabled ? tab.disabledReason : undefined}
            className={`flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium transition-colors duration-150 ${
              isActive
                ? "border-[var(--color-primary)] text-[var(--color-primary)]"
                : isDisabled
                  ? "cursor-not-allowed border-transparent text-[var(--color-text-tertiary)] opacity-40"
                  : "border-transparent text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]"
            }`}
          >
            {tab.icon}
            <span className="hidden sm:inline">{tab.label}</span>
          </button>
        );
      })}
    </div>
  );
}

// useToast hook for toast notifications
export interface ToastMessage {
  id: string;
  message: string;
  type: "success" | "error" | "info";
}

export function useToast() {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const showToast = useCallback(
    (message: string, type: "success" | "error" | "info" = "info") => {
      const id = `toast-${Date.now()}`;
      setToasts((prev) => [...prev, { id, message, type }]);
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, 3000);
    },
    [],
  );

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return { toasts, showToast, removeToast };
}

export function ToastContainer({
  toasts,
  onRemove,
}: {
  toasts: ToastMessage[];
  onRemove: (id: string) => void;
}) {
  const colorClasses = {
    success: "text-[var(--color-success)]",
    error: "text-[var(--color-error)]",
    info: "text-[var(--color-info)]",
  };

  return (
    <div className="fixed right-4 top-16 z-50 flex flex-col gap-2 md:right-6 md:top-20">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className="animate-slide-in-right flex items-center gap-2 rounded-lg border border-[var(--color-border)] bg-white px-4 py-3 shadow-lg"
        >
          <span className={`text-sm font-medium ${colorClasses[toast.type]}`}>
            {toast.message}
          </span>
          <button
            onClick={() => onRemove(toast.id)}
            className="ml-2 text-[var(--color-text-tertiary)] hover:text-[var(--color-text-primary)]"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
