"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Home, History, HelpCircle, Info, Settings } from "lucide-react";

const tabs = [
  { href: "/", label: "工作台", icon: Home },
  { href: "/history", label: "历史", icon: History },
  { href: "/help", label: "帮助", icon: HelpCircle },
  { href: "/about", label: "关于", icon: Info },
  { href: "/settings", label: "设置", icon: Settings },
];

export function BottomTabBar() {
  const pathname = usePathname();

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-40 grid h-14 grid-cols-5 border-t border-[var(--color-border)] bg-white md:hidden">
      {tabs.map((tab) => {
        const isActive =
          tab.href === "/"
            ? pathname === "/"
            : pathname.startsWith(tab.href);
        const Icon = tab.icon;
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={`flex flex-col items-center justify-center gap-0.5 transition-colors duration-150 ${
              isActive
                ? "text-[var(--color-primary)]"
                : "text-[var(--color-text-tertiary)]"
            }`}
          >
            <Icon className="h-5 w-5" />
            <span className="text-xs">{tab.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
