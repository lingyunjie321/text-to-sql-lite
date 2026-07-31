"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Database, Github } from "lucide-react";

const navItems = [
  { href: "/", label: "工作台" },
  { href: "/history", label: "历史" },
  { href: "/help", label: "帮助" },
  { href: "/settings", label: "设置" },
  { href: "/about", label: "关于" },
];

export function TopNav() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-40 hidden h-14 border-b border-[var(--color-border)] bg-white md:block">
      <div className="mx-auto flex h-full max-w-[1200px] items-center justify-between px-6">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2">
          <Database className="h-5 w-5 text-[var(--color-primary)]" />
          <span className="text-base font-semibold text-[var(--color-text-primary)]">
            Text-to-SQL
          </span>
        </Link>

        {/* Nav items */}
        <nav className="flex items-center gap-1">
          {navItems.map((item) => {
            const isActive =
              item.href === "/"
                ? pathname === "/"
                : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`relative rounded-md px-4 py-2 text-sm font-medium transition-colors duration-150 ${
                  isActive
                    ? "text-[var(--color-primary)]"
                    : "text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]"
                }`}
              >
                {item.label}
                {isActive && (
                  <span className="absolute bottom-0 left-1/2 h-0.5 w-8 -translate-x-1/2 rounded-full bg-[var(--color-primary)]" />
                )}
              </Link>
            );
          })}
        </nav>

        {/* Right side */}
        <a
          href="https://github.com"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 text-sm text-[var(--color-text-tertiary)] hover:text-[var(--color-text-primary)]"
        >
          <Github className="h-4 w-4" />
        </a>
      </div>
    </header>
  );
}
