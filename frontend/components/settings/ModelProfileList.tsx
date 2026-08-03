import { Pencil, Trash2 } from "lucide-react";

import { Button } from "../ui/Button";
import type { ModelProfileResponse } from "../../lib/model-profiles";

interface ModelProfileListProps {
  profiles: readonly ModelProfileResponse[];
  selectedId: string | null;
  onSelect: (profileId: string) => void;
  onEdit: (profile: ModelProfileResponse) => void;
  onDelete: (profile: ModelProfileResponse) => void;
}

function credentialLabel(status: "configured" | "missing"): string {
  return status === "configured" ? "已配置" : "缺失";
}

function embeddingLabel(profile: ModelProfileResponse): string {
  if (profile.embedding_credential_status === "not_applicable") {
    return "Embedding 未配置";
  }
  return `Embedding 已配置 · 凭据：${credentialLabel(profile.embedding_credential_status)}`;
}

export function ModelProfileList({
  profiles,
  selectedId,
  onSelect,
  onEdit,
  onDelete,
}: ModelProfileListProps) {
  return (
    <div className="space-y-3">
      {profiles.map((profile) => {
        const isSelected = profile.id === selectedId;
        return (
          <article
            key={profile.id}
            className={`rounded-lg border bg-white p-5 shadow-sm ${
              isSelected
                ? "border-[var(--color-primary)]"
                : "border-[var(--color-border)]"
            }`}
          >
            <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="font-medium text-[var(--color-text-primary)]">
                    {profile.name}
                  </h3>
                  {isSelected ? (
                    <span className="rounded-full bg-[var(--color-primary-light)] px-2 py-0.5 text-xs font-medium text-[var(--color-primary)]">
                      当前模型
                    </span>
                  ) : null}
                </div>
                <p className="mt-1 break-all font-mono text-sm text-[var(--color-text-secondary)]">
                  {profile.model_name}
                </p>
                <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--color-text-tertiary)]">
                  <span>
                    生成凭据：
                    {credentialLabel(profile.generation_credential_status)}
                  </span>
                  <span>{embeddingLabel(profile)}</span>
                </div>
              </div>

              <div className="flex shrink-0 flex-wrap gap-2">
                {!isSelected ? (
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    onClick={() => onSelect(profile.id)}
                  >
                    设为当前
                  </Button>
                ) : null}
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => onEdit(profile)}
                >
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
