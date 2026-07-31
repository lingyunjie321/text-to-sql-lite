"use client";

import { useState, useCallback } from "react";
import { Database, RotateCcw, Save, Plug, AlertTriangle } from "lucide-react";
import { PasswordInput } from "./PasswordInput";
import { Button } from "@/components/ui/Button";
import type { StoredDbConfig } from "@/lib/types";
import {
  getDefaultDbConfig,
  getDbConfig,
  setDbConfig,
  DEFAULT_PORTS,
  parseDsn,
  buildDsn,
} from "@/lib/datasource-config";

interface DatabaseConfigSectionProps {
  onToast: (message: string, type?: "success" | "info" | "error") => void;
}

type DbType = "postgresql" | "mysql" | "starrocks";

const dbTypes: { value: DbType; label: string }[] = [
  { value: "postgresql", label: "PostgreSQL" },
  { value: "mysql", label: "MySQL" },
  { value: "starrocks", label: "StarRocks" },
];

export function DatabaseConfigSection({ onToast }: DatabaseConfigSectionProps) {
  const [config, setConfig] = useState<StoredDbConfig>(() => getDbConfig());

  const updateConnection = useCallback(
    (patch: Partial<StoredDbConfig["connection"]>) => {
      setConfig((prev) => ({
        ...prev,
        connection: { ...prev.connection, ...patch },
      }));
    },
    [],
  );

  const handleTypeChange = useCallback((type: DbType) => {
    setConfig((prev) => ({
      ...prev,
      type,
      connection: {
        ...prev.connection,
        port: DEFAULT_PORTS[type],
      },
    }));
  }, []);

  const handleModeSwitch = useCallback(() => {
    setConfig((prev) => {
      if (prev.connection.mode === "form") {
        // form -> dsn: try to build DSN
        const conn = prev.connection;
        const dsn = buildDsn({
          type: prev.type,
          username: conn.username ?? "",
          password: conn.password ?? "",
          host: conn.host ?? "",
          port: conn.port ?? DEFAULT_PORTS[prev.type],
          database: conn.database ?? "",
        });
        return {
          ...prev,
          connection: { ...conn, mode: "dsn", dsn },
        };
      } else {
        // dsn -> form: try to parse DSN
        const parsed = parseDsn(prev.connection.dsn ?? "");
        if (!parsed) {
          onToast("无法解析 DSN，请检查格式", "error");
          return prev;
        }
        return {
          ...prev,
          type: parsed.type,
          connection: {
            mode: "form",
            host: parsed.host,
            port: parsed.port,
            database: parsed.database,
            username: parsed.username,
            password: parsed.password,
          },
        };
      }
    });
  }, [onToast]);

  const handleTest = useCallback(() => {
    onToast("此功能需要后端支持，暂不可用", "info");
  }, [onToast]);

  const validateConfig = (cfg: StoredDbConfig): string | null => {
    if (!/^[a-z0-9_-]+$/.test(cfg.datasource_id)) {
      return "数据源 ID 只能包含小写字母、数字、下划线和连字符";
    }
    if (cfg.connection.mode === "form") {
      const conn = cfg.connection;
      if (!conn.host?.trim()) return "主机地址不能为空";
      if (!conn.database?.trim()) return "数据库名不能为空";
      if (!conn.username?.trim()) return "用户名不能为空";
      if (!conn.port || conn.port < 1 || conn.port > 65535) {
        return "端口号必须在 1-65535 范围内";
      }
    } else {
      if (!cfg.connection.dsn?.trim()) return "DSN 连接字符串不能为空";
    }
    return null;
  };

  const handleSave = useCallback(() => {
    const error = validateConfig(config);
    if (error) {
      onToast(error, "error");
      return;
    }
    setDbConfig(config);
    onToast("配置已保存", "success");
  }, [config, onToast]);

  const handleReset = useCallback(() => {
    setConfig(getDefaultDbConfig());
    onToast("已重置为默认值，请点击保存以生效", "info");
  }, [onToast]);

  const conn = config.connection;
  const isForm = conn.mode === "form";

  return (
    <div>
      <h2 className="text-xl font-semibold text-[var(--color-text-primary)]">
        数据库配置
      </h2>
      <p className="mt-1 text-sm text-[var(--color-text-tertiary)]">
        配置 Text-to-SQL Agent 连接的数据库
      </p>

      {/* Datasource type selector */}
      <div className="mt-6">
        <label className="mb-2 block text-sm font-medium text-[var(--color-text-secondary)]">
          数据源类型
        </label>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {dbTypes.map((t) => {
            const selected = config.type === t.value;
            return (
              <button
                key={t.value}
                type="button"
                onClick={() => handleTypeChange(t.value)}
                className={`flex items-center justify-center gap-2 rounded-md border p-3 text-sm font-medium transition-colors duration-150 ${
                  selected
                    ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] text-[var(--color-primary)]"
                    : "border-[var(--color-border)] bg-white text-[var(--color-text-secondary)] hover:border-[var(--color-border-strong)]"
                }`}
              >
                <Database className="h-4 w-4" />
                {t.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Connection config */}
      <div className="mt-6">
        <div className="mb-2 flex items-center justify-between">
          <label className="text-sm font-medium text-[var(--color-text-secondary)]">
            连接配置
          </label>
          <button
            type="button"
            onClick={handleModeSwitch}
            className="text-sm text-[var(--color-primary)] hover:underline"
          >
            {isForm ? "高级模式 ▸" : "表单模式 ▸"}
          </button>
        </div>

        {isForm ? (
          <div className="rounded-lg border border-[var(--color-border)] bg-white p-5 shadow-sm">
            <div className="grid grid-cols-3 gap-4">
              <div className="col-span-2">
                <label className="mb-1.5 block text-sm font-medium text-[var(--color-text-secondary)]">
                  主机地址 (Host)
                </label>
                <input
                  type="text"
                  value={conn.host ?? ""}
                  onChange={(e) => updateConnection({ host: e.target.value })}
                  placeholder="localhost"
                  className="h-10 w-full rounded-md border border-[var(--color-border-strong)] bg-white px-3 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:border-[var(--color-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-sm font-medium text-[var(--color-text-secondary)]">
                  端口 (Port)
                </label>
                <input
                  type="number"
                  value={conn.port ?? ""}
                  onChange={(e) =>
                    updateConnection({
                      port: parseInt(e.target.value, 10) || 0,
                    })
                  }
                  placeholder="5432"
                  className="h-10 w-full rounded-md border border-[var(--color-border-strong)] bg-white px-3 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:border-[var(--color-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20"
                />
              </div>
            </div>
            <div className="mt-3">
              <label className="mb-1.5 block text-sm font-medium text-[var(--color-text-secondary)]">
                数据库名 (Database)
              </label>
              <input
                type="text"
                value={conn.database ?? ""}
                onChange={(e) => updateConnection({ database: e.target.value })}
                placeholder="pagila"
                className="h-10 w-full rounded-md border border-[var(--color-border-strong)] bg-white px-3 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:border-[var(--color-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20"
              />
            </div>
            <div className="mt-3">
              <label className="mb-1.5 block text-sm font-medium text-[var(--color-text-secondary)]">
                用户名 (Username)
              </label>
              <input
                type="text"
                value={conn.username ?? ""}
                onChange={(e) => updateConnection({ username: e.target.value })}
                placeholder="postgres"
                className="h-10 w-full rounded-md border border-[var(--color-border-strong)] bg-white px-3 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:border-[var(--color-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20"
              />
            </div>
            <div className="mt-3">
              <label className="mb-1.5 block text-sm font-medium text-[var(--color-text-secondary)]">
                密码 (Password)
              </label>
              <PasswordInput
                value={conn.password ?? ""}
                onChange={(password) => updateConnection({ password })}
              />
            </div>
          </div>
        ) : (
          <div className="rounded-lg border border-[var(--color-border)] bg-white p-5 shadow-sm">
            <label className="mb-1.5 block text-sm font-medium text-[var(--color-text-secondary)]">
              DSN 连接字符串
            </label>
            <textarea
              value={conn.dsn ?? ""}
              onChange={(e) => updateConnection({ dsn: e.target.value })}
              placeholder="postgresql://postgres:password@localhost:5432/pagila"
              rows={3}
              className="w-full min-h-20 resize-none rounded-md border border-[var(--color-border-strong)] bg-white p-3 font-mono text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:border-[var(--color-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20"
            />
            <p className="mt-2 text-xs text-[var(--color-text-tertiary)]">
              直接填写完整 DSN，适用于复杂连接参数
            </p>
          </div>
        )}
      </div>

      {/* Auth config */}
      <div className="mt-6">
        <label className="mb-2 block text-sm font-medium text-[var(--color-text-secondary)]">
          授权配置
        </label>
        <div className="space-y-3 rounded-lg border border-[var(--color-border)] bg-white p-5 shadow-sm">
          <div>
            <label className="mb-1.5 block text-sm font-medium text-[var(--color-text-secondary)]">
              Schema 列表（逗号分隔）
            </label>
            <input
              type="text"
              value={config.auth.schemas.join(", ")}
              onChange={(e) =>
                setConfig((prev) => ({
                  ...prev,
                  auth: {
                    ...prev.auth,
                    schemas: e.target.value
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean),
                  },
                }))
              }
              placeholder="public, sales"
              className="h-10 w-full rounded-md border border-[var(--color-border-strong)] bg-white px-3 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:border-[var(--color-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20"
            />
            <p className="mt-1 text-xs text-[var(--color-text-tertiary)]">
              限制 Agent 只能访问指定 Schema，留空表示全部
            </p>
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium text-[var(--color-text-secondary)]">
              授权表列表（可选，逗号分隔）
            </label>
            <input
              type="text"
              value={config.auth.allowed_tables.join(", ")}
              onChange={(e) =>
                setConfig((prev) => ({
                  ...prev,
                  auth: {
                    ...prev.auth,
                    allowed_tables: e.target.value
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean),
                  },
                }))
              }
              placeholder="payment, rental, customer"
              className="h-10 w-full rounded-md border border-[var(--color-border-strong)] bg-white px-3 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:border-[var(--color-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20"
            />
            <p className="mt-1 text-xs text-[var(--color-text-tertiary)]">
              限制 Agent 只能查询指定表，留空表示全部
            </p>
          </div>
        </div>
      </div>

      {/* Datasource ID */}
      <div className="mt-6">
        <label className="mb-2 block text-sm font-medium text-[var(--color-text-secondary)]">
          数据源标识
        </label>
        <div className="rounded-lg border border-[var(--color-border)] bg-white p-5 shadow-sm">
          <label className="mb-1.5 block text-sm font-medium text-[var(--color-text-secondary)]">
            数据源 ID (Datasource ID)
          </label>
          <input
            type="text"
            value={config.datasource_id}
            onChange={(e) =>
              setConfig((prev) => ({ ...prev, datasource_id: e.target.value }))
            }
            placeholder="my-postgres"
            className="h-10 w-full rounded-md border border-[var(--color-border-strong)] bg-white px-3 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:border-[var(--color-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20"
          />
          <p className="mt-1 flex items-start gap-1 text-xs text-[var(--color-text-tertiary)]">
            <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
            查询时通过此 ID 指定数据源（需要后端支持动态注册）
          </p>
        </div>
      </div>

      {/* Test + actions */}
      <div className="mt-6 flex justify-end gap-3">
        <Button variant="secondary" size="sm" onClick={handleTest}>
          <Plug className="h-3.5 w-3.5" />
          测试连接
        </Button>
      </div>
      <div className="mt-3 flex justify-end gap-3">
        <Button variant="secondary" onClick={handleReset}>
          <RotateCcw className="h-4 w-4" />
          重置默认
        </Button>
        <Button onClick={handleSave}>
          <Save className="h-4 w-4" />
          保存配置
        </Button>
      </div>
    </div>
  );
}
