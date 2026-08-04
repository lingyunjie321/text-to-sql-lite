import { Pencil, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/Button";
import type { DatasourceProfileResponse } from "@/lib/datasource-profiles";

interface Props {
  profiles: readonly DatasourceProfileResponse[];
  selectedId: string | null;
  onSelect: (profileId: string) => void;
  onEdit: (profile: DatasourceProfileResponse) => void;
  onDelete: (profile: DatasourceProfileResponse) => void;
}

export function DatasourceProfileList({
  profiles,
  selectedId,
  onSelect,
  onEdit,
  onDelete,
}: Props) {
  return (
    <div className="space-y-3">
      {profiles.map((profile) => {
        const selected = profile.id === selectedId;
        return (
          <article
            key={profile.id}
            className={`rounded-lg border bg-white p-5 shadow-sm ${
              selected
                ? "border-[var(--color-primary)]"
                : "border-[var(--color-border)]"
            }`}
          >
            <div className="flex flex-col gap-4 sm:flex-row sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="font-medium text-[var(--color-text-primary)]">
                    {profile.name}
                  </h3>
                  {selected ? (
                    <span className="rounded-full bg-[var(--color-primary-light)] px-2 py-0.5 text-xs font-medium text-[var(--color-primary)]">
                      当前数据源
                    </span>
                  ) : null}
                </div>
                <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
                  {profile.database_type === "postgresql" ? "PostgreSQL" : "MySQL"}
                  {" · "}
                  {profile.host}:{profile.port}/{profile.database}
                </p>
                <p className="mt-2 text-xs text-[var(--color-text-tertiary)]">
                  已授权 {profile.allowed_tables.length} 个表或视图 · 密码
                  {profile.password_status === "configured" ? "已配置" : "缺失"}
                </p>
              </div>
              <div className="flex shrink-0 flex-wrap gap-2">
                {!selected ? (
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    onClick={() => onSelect(profile.id)}
                  >
                    设为当前
                  </Button>
                ) : null}
                <Button type="button" variant="ghost" size="sm" onClick={() => onEdit(profile)}>
                  <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                  编辑
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="text-[var(--color-error)]"
                  onClick={() => onDelete(profile)}
                >
                  <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                  删除
                </Button>
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}
