"use client";

import { useState, useCallback, useEffect } from "react";
import { Cpu, Database, Info } from "lucide-react";
import { ModelProfileSection } from "./ModelProfileSection";
import { DatasourceProfileSection } from "./DatasourceProfileSection";
import { AboutSection } from "./AboutSection";
import { modelProfileCountStatus } from "./model-profile-coordinator";
import { removeLegacyDatasourceConfig } from "@/lib/profile-selection";

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
  const [configVersion, setConfigVersion] = useState(0);
  const [modelProfileCount, setModelProfileCount] = useState<
    number | null | undefined
  >(undefined);
  const [datasourceProfileCount, setDatasourceProfileCount] = useState<
    number | null | undefined
  >(undefined);

  useEffect(() => {
    removeLegacyDatasourceConfig();
  }, []);

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

  const handleConfigCleared = useCallback(() => {
    setConfigVersion((v) => v + 1);
  }, []);

  const statusFor = (id: SectionId): string | null => {
    if (id === "models") {
      return modelProfileCountStatus(modelProfileCount);
    }
    if (id === "database") {
      return modelProfileCountStatus(datasourceProfileCount);
    }
    return null;
  };

  const renderSection = (id: SectionId) => {
    switch (id) {
      case "models":
        return (
          <ModelProfileSection
            onToast={showToast}
            onProfileCountChange={setModelProfileCount}
          />
        );
      case "database":
        return (
          <DatasourceProfileSection
            key={configVersion}
            onToast={showToast}
            onProfileCountChange={setDatasourceProfileCount}
          />
        );
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

      <div className="md:flex md:gap-6">
        {/* Sidebar */}
        <aside className="hidden w-56 shrink-0 md:block">
          <nav className="space-y-1">
            {navItems.map((item) => {
              const { Icon } = item;
              const isActive = activeSection === item.id;
              const badge = statusFor(item.id);
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

        <div className="min-w-0 flex-1">
          {/* Mobile: navigation only. Content is mounted once below. */}
          <nav className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-3 md:hidden">
            {navItems.map((item) => {
              const { Icon } = item;
              const isActive = activeSection === item.id;
              const badge = statusFor(item.id);
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setActiveSection(item.id)}
                  className={`flex w-full items-center justify-between rounded-lg border px-4 py-3 text-left shadow-sm ${
                    isActive
                      ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]"
                      : "border-[var(--color-border)] bg-white"
                  }`}
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
                  </span>
                </button>
              );
            })}
          </nav>

          {/* Shared desktop/mobile content instance. */}
          {renderSection(activeSection)}
        </div>
      </div>
    </div>
  );
}
