interface UserMessageProps {
  text: string;
  isSupplement?: boolean;
}

export function UserMessage({ text, isSupplement = false }: UserMessageProps) {
  return (
    <div className="flex justify-end">
      <div
        className={`max-w-[80%] rounded-2xl rounded-br-md px-4 py-3 text-sm ${
          isSupplement
            ? "bg-[var(--color-warning-light)] text-[var(--color-text-primary)]"
            : "bg-[var(--color-primary-light)] text-[var(--color-text-primary)]"
        }`}
      >
        {isSupplement && (
          <span className="mb-1 block text-xs font-medium text-[var(--color-warning)]">
            补充说明
          </span>
        )}
        <p className="whitespace-pre-wrap break-words">{text}</p>
      </div>
    </div>
  );
}
