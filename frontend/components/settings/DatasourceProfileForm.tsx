"use client";

import { useEffect, useState } from "react";
import { Database } from "lucide-react";

import { Button } from "@/components/ui/Button";
import {
  buildDatasourceWriteRequest,
  createDatasourceProfile,
  getDatasourceMetadata,
  replaceDatasourceProfile,
  testDatasourceConnection,
  type DatasourceProfileFormValue,
  type DatasourceProfileResponse,
  type MetadataSchema,
} from "@/lib/datasource-profiles";
import { PasswordInput } from "./PasswordInput";
import { DatasourceSchemaTree } from "./DatasourceSchemaTree";

export { DatasourceSchemaTree } from "./DatasourceSchemaTree";

interface FormProps {
  mode: "create" | "edit";
  profile?: DatasourceProfileResponse;
  onSaved: (profile: DatasourceProfileResponse) => void;
  onCancel: () => void;
}

const fieldClass =
  "h-10 w-full rounded-md border border-[var(--color-border-strong)] bg-white px-3 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 disabled:bg-[var(--color-bg-muted)]";

function createValue(profile?: DatasourceProfileResponse): DatasourceProfileFormValue {
  return {
    id: profile?.id ?? "",
    name: profile?.name ?? "",
    databaseType: profile?.database_type ?? "postgresql",
    host: profile?.host ?? "localhost",
    port: profile?.port ?? 5432,
    database: profile?.database ?? "",
    username: profile?.username ?? "",
    password: "",
    clearPassword: false,
    allowedTables: profile ? [...profile.allowed_tables] : [],
  };
}

function connectionError(value: DatasourceProfileFormValue): string | null {
  if (!value.host.trim()) return "请输入主机地址";
  const port = Number(value.port);
  if (!Number.isInteger(port) || port < 1 || port > 65535) return "端口必须在 1 到 65535 之间";
  if (!value.database.trim()) return "请输入数据库名";
  if (!value.username.trim()) return "请输入用户名";
  return null;
}

function saveError(value: DatasourceProfileFormValue): string | null {
  if (!/^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$/.test(value.id)) {
    return "Profile ID 只能包含小写字母、数字、下划线和连字符";
  }
  if (!value.name.trim()) return "请输入 Profile 名称";
  return connectionError(value) ??
    (value.allowedTables.length === 0 ? "请至少勾选一个允许查询的表或视图" : null);
}

function schemasFromTest(
  schemas: readonly string[],
  relations: readonly { schema: string; name: string; kind: "table" | "view" }[],
): MetadataSchema[] {
  return schemas.map((schema) => ({
    name: schema,
    relations: relations
      .filter((relation) => relation.schema === schema)
      .map((relation) => ({
        name: relation.name,
        kind: relation.kind,
        columns: [],
        primary_key: [],
      })),
  }));
}

export function DatasourceProfileForm({ mode, profile, onSaved, onCancel }: FormProps) {
  const [value, setValue] = useState(() => createValue(profile));
  const [schemas, setSchemas] = useState<MetadataSchema[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState<"metadata" | "test" | "save" | null>(
    mode === "edit" ? "metadata" : null,
  );

  useEffect(() => {
    if (mode !== "edit" || !profile) return;
    let active = true;
    getDatasourceMetadata(profile.id).then(
      (metadata) => {
        if (!active) return;
        setSchemas(metadata.schemas);
        setStatus(metadata.truncated ? "metadata 已截断，请缩小授权范围。" : null);
        setBusy(null);
      },
      () => {
        if (!active) return;
        setStatus("无法获取 metadata；请重新测试连接。");
        setBusy(null);
      },
    );
    return () => {
      active = false;
    };
  }, [mode, profile]);

  const patchValue = (patch: Partial<DatasourceProfileFormValue>) => {
    setValue((current) => ({ ...current, ...patch }));
    setStatus(null);
  };

  const handleDatabaseType = (databaseType: "postgresql" | "mysql") => {
    patchValue({
      databaseType,
      port: databaseType === "postgresql" ? 5432 : 3306,
    });
  };

  const handleToggle = (qualifiedName: string) => {
    setValue((current) => ({
      ...current,
      allowedTables: current.allowedTables.includes(qualifiedName)
        ? current.allowedTables.filter((table) => table !== qualifiedName)
        : [...current.allowedTables, qualifiedName],
    }));
  };

  const handleTest = async () => {
    const error = connectionError(value);
    if (error) {
      setStatus(error);
      return;
    }
    setBusy("test");
    setStatus(null);
    try {
      const result = await testDatasourceConnection({
        database_type: value.databaseType,
        host: value.host,
        port: Number(value.port),
        database: value.database,
        username: value.username,
        password: value.password,
      });
      const discoveredSchemas = schemasFromTest(result.schemas, result.relations);
      const discoveredTables = new Set(
        result.relations.map((relation) => `${relation.schema}.${relation.name}`),
      );
      setSchemas(discoveredSchemas);
      setValue((current) => ({
        ...current,
        allowedTables: current.allowedTables.filter((table) => discoveredTables.has(table)),
      }));
      setStatus(
        result.truncated
          ? "连接成功，但 metadata 已截断。"
          : "连接成功，请勾选允许查询的表或视图。",
      );
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "数据库连接测试失败。");
    } finally {
      setBusy(null);
    }
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const error = saveError(value);
    if (error) {
      setStatus(error);
      return;
    }
    setBusy("save");
    setStatus(null);
    try {
      const request = buildDatasourceWriteRequest(value, { mode });
      const saved = mode === "create"
        ? await createDatasourceProfile(request)
        : await replaceDatasourceProfile(value.id, request);
      onSaved(saved);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "保存数据源 Profile 失败。");
    } finally {
      setBusy(null);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="rounded-lg border border-[var(--color-border)] bg-white p-5 shadow-sm">
      <h3 className="font-semibold text-[var(--color-text-primary)]">
        {mode === "create" ? "添加数据源 Profile" : "编辑数据源 Profile"}
      </h3>

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <label className="text-sm text-[var(--color-text-secondary)]">
          Profile ID
          <input
            name="id"
            className={`${fieldClass} mt-1.5`}
            value={value.id}
            readOnly={mode === "edit"}
            onChange={(event) => patchValue({ id: event.target.value })}
          />
        </label>
        <label className="text-sm text-[var(--color-text-secondary)]">
          名称
          <input
            className={`${fieldClass} mt-1.5`}
            value={value.name}
            onChange={(event) => patchValue({ name: event.target.value })}
          />
        </label>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3">
        {(["postgresql", "mysql"] as const).map((databaseType) => (
          <button
            key={databaseType}
            type="button"
            className={`flex items-center justify-center gap-2 rounded-md border p-3 text-sm font-medium ${
              value.databaseType === databaseType
                ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] text-[var(--color-primary)]"
                : "border-[var(--color-border)] text-[var(--color-text-secondary)]"
            }`}
            onClick={() => handleDatabaseType(databaseType)}
          >
            <Database className="h-4 w-4" />
            {databaseType === "postgresql" ? "PostgreSQL" : "MySQL"}
          </button>
        ))}
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-3">
        <label className="sm:col-span-2 text-sm text-[var(--color-text-secondary)]">
          Host
          <input className={`${fieldClass} mt-1.5`} value={value.host} onChange={(event) => patchValue({ host: event.target.value })} />
        </label>
        <label className="text-sm text-[var(--color-text-secondary)]">
          Port
          <input className={`${fieldClass} mt-1.5`} inputMode="numeric" value={value.port} onChange={(event) => patchValue({ port: event.target.value })} />
        </label>
        <label className="text-sm text-[var(--color-text-secondary)]">
          数据库
          <input className={`${fieldClass} mt-1.5`} value={value.database} onChange={(event) => patchValue({ database: event.target.value })} />
        </label>
        <label className="text-sm text-[var(--color-text-secondary)]">
          用户名
          <input className={`${fieldClass} mt-1.5`} value={value.username} autoComplete="username" onChange={(event) => patchValue({ username: event.target.value })} />
        </label>
        <label className="text-sm text-[var(--color-text-secondary)]">
          密码
          <div className="mt-1.5">
            <PasswordInput
              value={value.password}
              onChange={(password) => patchValue({ password, clearPassword: false })}
              autoComplete="new-password"
              placeholder={mode === "edit" ? "留空则保留当前密码" : "可留空"}
            />
          </div>
        </label>
      </div>

      {mode === "edit" && profile?.password_status === "configured" ? (
        <label className="mt-3 flex items-center gap-2 text-sm text-[var(--color-text-secondary)]">
          <input
            type="checkbox"
            checked={value.clearPassword}
            onChange={(event) => patchValue({ clearPassword: event.target.checked, password: "" })}
          />
          清除后端进程内保存的密码
        </label>
      ) : null}

      <div className="mt-5 flex items-center gap-3">
        <Button type="button" variant="secondary" loading={busy === "test"} onClick={handleTest}>
          测试连接并获取结构
        </Button>
        <span className="text-xs text-[var(--color-text-tertiary)]">
          密码只随本次请求发送，不写入浏览器。
        </span>
      </div>

      {schemas.length > 0 ? (
        <div className="mt-6">
          <div className="mb-2 flex items-center justify-between">
            <h4 className="text-sm font-medium text-[var(--color-text-secondary)]">
              允许 AI 查询的表和视图
            </h4>
            <span className="text-xs text-[var(--color-text-tertiary)]">
              已选择 {value.allowedTables.length} 个
            </span>
          </div>
          <DatasourceSchemaTree schemas={schemas} selectedTables={value.allowedTables} onToggle={handleToggle} />
        </div>
      ) : null}

      {status ? (
        <p role="status" className="mt-4 rounded-md bg-[var(--color-bg-subtle)] px-3 py-2 text-sm text-[var(--color-text-secondary)]">
          {status}
        </p>
      ) : null}

      <div className="mt-6 flex justify-end gap-3">
        <Button type="button" variant="ghost" onClick={onCancel}>取消</Button>
        <Button type="submit" loading={busy === "save"}>保存 Profile</Button>
      </div>
    </form>
  );
}
