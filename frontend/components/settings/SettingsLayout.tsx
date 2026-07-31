"use client";

import { useState, useCallback, useEffect } from "react";
import { Cpu, Database, Info, ChevronDown } from "lucide-react";
import { ModelConfigSection } from "./ModelConfigSection";
import { DatabaseConfigSection } from "./DatabaseConfigSection";
import { AboutSection } from "./AboutSection";
import { getModelConfig, isModelConfigured } from "@/lib/model-config";
import { getDbConfig, isDbConfigured } from "@/lib/datasource-config";

type SectionId = "models" | "database" | "about";

interface NavItem {
  id: SectionId;
  label: string;
  Icon: typeof Cpu;
}

const navItems: NavItem[] = [
  { id: "models", label: "模型配置", Icon: Cpu },
  { id: "database", label: "数据库配置", Icon: Database },
  { id: "about", label: "关于", Icon: Info },
];

interface ToastState {
  message: string;
  type: "success" | "info" | "error";
  id: number;
}

export function SettingsLayout() {
  const [activeSection, setActiveSection] = useState<SectionId>("models");
  const [toast, setToast] = useState<ToastState | null>(null);
  const [mobileExpanded, setMobileExpanded] = useState<Set<SectionId>>(
    new Set(["models"]),
  );
  const [configVersion, setConfigVersion] = useState(0);

  const showToast = useCallback(
    (message: string, type: "success" | "info" | "error" = "info") => {
      setToast({ message, type, id: Date.now() });
    },
    [],
  );

  // Auto-dismiss toast
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(timer);
  }, [toast]);

  const toggleMobile = useCallback((id: SectionId) => {
    setMobileExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const handleConfigCleared = useCallback(() => {
    setConfigVersion((v) => v + 1);
  }, []);

  // Status badges for sidebar
  const modelConfigured = (() => {
    try {
      return isModelConfigured(getModelConfig());
    } catch {
      return false;
    }
  })();
  const dbConfigured = (() => {
    try {
      return isDbConfigured(getDbConfig());
    } catch {
      return false;
    }
  })();

  const renderSection = (id: SectionId) => {
    switch (id) {
      case "models":
        return <ModelConfigSection key={configVersion} onToast={showToast} />;
      case "database":
        return <DatabaseConfigSection key={configVersion} onToast={showToast} />;
      case "about":
        return (
          <AboutSection
            onToast={showToast}
            onConfigCleared={handleConfigCleared}
          />
        );
    }
  };

  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 py-6 md:px-6">
      <h1 className="mb-6 text-2xl font-bold text-[var(--color-text-primary)]">
        设置
      </h1>

      {/* Toast */}
      {toast && (
        <div
          className={`fixed right-4 top-16 z-50 animate-fade-in rounded-md px-4 py-2.5 text-sm shadow-lg ${
            toast.type === "success"
              ? "bg-[var(--color-success)] text-white"
              : toast.type === "error"
                ? "bg-[var(--color-error)] text-white"
                : "bg-[var(--color-text-primary)] text-white"
          }`}
        >
          {toast.message}
        </div>
      )}

      {/* Desktop: sidebar + content */}
      <div className="hidden gap-6 md:flex">
        {/* Sidebar */}
        <aside className="w-56 shrink-0">
          <nav className="space-y-1">
            {navItems.map((item) => {
              const { Icon } = item;
              const isActive = activeSection === item.id;
              const badge =
                item.id === "models"
                  ? modelConfigured
                    ? "已配置"
                    : "未配置"
                  : item.id === "database"
                    ? dbConfigured
                      ? "已配置"
                      : "未配置"
                    : null;
              return (
                <button
                  key={item.id}
                  onClick={() => setActiveSection(item.id)}
                  className={`flex w-full items-center justify-between border-l-2 px-4 py-3 text-sm transition-colors duration-150 ${
                    isActive
                      ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] text-[var(--color-primary)]"
                      : "border-transparent text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-subtle)]"
                  }`}
                >
                  <span className="flex items-center gap-2">
                    <Icon className="h-4 w-4" />
                    {item.label}
                  </span>
                  {badge && (
                    <span
                      className={`text-xs ${
                        badge === "已配置"
                          ? "text-[var(--color-success)]"
                          : "text-[var(--color-text-tertiary)]"
                      }`}
                    >
                      {badge}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>
        </aside>

        {/* Content */}
        <div className="min-w-0 flex-1">
          {renderSection(activeSection)}
        </div>
      </div>

      {/* Mobile: accordion */}
      <div className="space-y-3 md:hidden">
        {navItems.map((item) => {
          const { Icon } = item;
          const isExpanded = mobileExpanded.has(item.id);
          const badge =
            item.id === "models"
              ? modelConfigured
                ? "已配置"
                : "未配置"
              : item.id === "database"
                ? dbConfigured
                  ? "已配置"
                  : "未配置"
                : null;
          return (
            <div
              key={item.id}
              className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-white shadow-sm"
            >
              <button
                onClick={() => toggleMobile(item.id)}
                className="flex w-full items-center justify-between px-4 py-3"
              >
                <span className="flex items-center gap-2 text-sm font-medium text-[var(--color-text-primary)]">
                  <Icon className="h-4 w-4 text-[var(--color-text-tertiary)]" />
                  {item.label}
                </span>
                <span className="flex items-center gap-2">
                  {badge && (
                    <span
                      className={`text-xs ${
                        badge === "已配置"
                          ? "text-[var(--color-success)]"
                          : "text-[var(--color-text-tertiary)]"
                      }`}
                    >
                      {badge}
                    </span>
                  )}
                  <ChevronDown
                    className={`h-4 w-4 text-[var(--color-text-tertiary)] transition-transform duration-150 ${
                      isExpanded ? "rotate-180" : ""
                    }`}
                  />
                </span>
              </button>
              {isExpanded && (
                <div className="border-t border-[var(--color-border)] p-4">
                  {renderSection(item.id)}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
