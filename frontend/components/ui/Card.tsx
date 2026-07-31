interface CardProps {
  children: React.ReactNode;
  className?: string;
  padding?: "sm" | "md" | "lg";
}

const paddingClasses = {
  sm: "p-4",
  md: "p-5",
  lg: "p-6",
};

export function Card({
  children,
  className = "",
  padding = "md",
}: CardProps) {
  return (
    <div
      className={`rounded-lg border border-[var(--color-border)] bg-white shadow-sm ${paddingClasses[padding]} ${className}`}
    >
      {children}
    </div>
  );
}
