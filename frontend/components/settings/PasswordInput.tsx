"use client";

import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";

interface PasswordInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  id?: string;
}

export function PasswordInput({
  value,
  onChange,
  placeholder = "••••••••",
  disabled = false,
  id,
}: PasswordInputProps) {
  const [visible, setVisible] = useState(false);

  return (
    <div className="flex">
      <input
        id={id}
        type={visible ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        className="h-10 flex-1 rounded-l-md border border-r-0 border-[var(--color-border-strong)] bg-white px-3 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:border-[var(--color-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 disabled:cursor-not-allowed disabled:bg-[var(--color-bg-muted)] disabled:text-[var(--color-text-tertiary)]"
        autoComplete="off"
      />
      <button
        type="button"
        onClick={() => setVisible(!visible)}
        disabled={disabled}
        className="flex w-10 items-center justify-center rounded-r-md border border-[var(--color-border-strong)] text-[var(--color-text-tertiary)] transition-colors duration-150 hover:text-[var(--color-text-primary)] disabled:cursor-not-allowed"
        aria-label={visible ? "隐藏密码" : "显示密码"}
      >
        {visible ? (
          <EyeOff className="h-4 w-4" />
        ) : (
          <Eye className="h-4 w-4" />
        )}
      </button>
    </div>
  );
}
