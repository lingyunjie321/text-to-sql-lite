"use client";

import { Plus, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Button } from "../ui/Button";
import {
  deleteModelProfile,
  listModelProfiles,
  ProfileApiError,
  type ModelProfileResponse,
} from "../../lib/model-profiles";
import {
  clearSelectedModelProfileId,
  getSelectedModelProfileId,
  reconcileSelectedModelProfileId,
  removeLegacyModelConfig,
  setSelectedModelProfileId,
} from "../../lib/profile-selection";
import { ModelProfileDeleteDialog } from "./ModelProfileDeleteDialog";
import { ModelProfileList } from "./ModelProfileList";
import {
  deleteModelProfileFromState,
  loadModelProfileState,
  type ModelProfileState,
} from "./model-profile-coordinator";

interface ModelProfileSectionProps {
  onToast: (message: string, type?: "success" | "info" | "error") => void;
  onProfileCountChange: (count: number | null) => void;
}

function isMissingProfileError(error: unknown): boolean {
  return (
    error instanceof ProfileApiError &&
    (error.code === "MODEL_PROFILE_NOT_FOUND" ||
      error.code === "PROFILE_NOT_FOUND")
  );
}

const loadDependencies = {
  removeLegacyConfig: removeLegacyModelConfig,
  listProfiles: listModelProfiles,
  reconcileSelectedId: reconcileSelectedModelProfileId,
};

const deleteDependencies = {
  deleteProfile: deleteModelProfile,
  listProfiles: listModelProfiles,
  getSelectedId: getSelectedModelProfileId,
  clearSelectedId: clearSelectedModelProfileId,
  reconcileSelectedId: reconcileSelectedModelProfileId,
  isMissingError: isMissingProfileError,
};

export function ModelProfileSection({
  onToast,
  onProfileCountChange,
}: ModelProfileSectionProps) {
  const [profiles, setProfiles] = useState<ModelProfileResponse[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [deleteTarget, setDeleteTarget] =
    useState<ModelProfileResponse | null>(null);
  const [deleteSubmitting, setDeleteSubmitting] = useState(false);

  const handleProfilesLoaded = useCallback(
    (state: ModelProfileState) => {
      setProfiles(state.profiles);
      setSelectedId(state.selectedId);
      setLoadFailed(false);
      setLoading(false);
      onProfileCountChange(state.profileCount);
    },
    [onProfileCountChange],
  );

  const handleProfilesLoadFailure = useCallback(() => {
    setProfiles([]);
    setLoadFailed(true);
    setLoading(false);
    onProfileCountChange(null);
  }, [onProfileCountChange]);

  const refreshProfiles = useCallback(async () => {
    try {
      handleProfilesLoaded(await loadModelProfileState(loadDependencies));
    } catch {
      handleProfilesLoadFailure();
    }
  }, [handleProfilesLoadFailure, handleProfilesLoaded]);

  useEffect(() => {
    let active = true;
    loadModelProfileState(loadDependencies).then(
      (state) => {
        if (active) handleProfilesLoaded(state);
      },
      () => {
        if (active) handleProfilesLoadFailure();
      },
    );
    return () => {
      active = false;
    };
  }, [handleProfilesLoadFailure, handleProfilesLoaded]);

  const handleSelect = useCallback(
    (profileId: string) => {
      setSelectedModelProfileId(profileId);
      setSelectedId(profileId);
      onToast("已设为当前模型", "success");
    },
    [onToast],
  );

  const handleEdit = useCallback(() => {
    onToast("模型编辑表单将在下一步提供", "info");
  }, [onToast]);

  const handleAdd = useCallback(() => {
    onToast("模型创建表单将在下一步提供", "info");
  }, [onToast]);

  const handleRetry = useCallback(() => {
    setLoading(true);
    setLoadFailed(false);
    void refreshProfiles();
  }, [refreshProfiles]);

  const handleConfirmDelete = useCallback(async () => {
    if (!deleteTarget || deleteSubmitting) return;

    setDeleteSubmitting(true);
    try {
      const result = await deleteModelProfileFromState(
        profiles,
        deleteTarget.id,
        deleteDependencies,
      );
      handleProfilesLoaded(result);
      setDeleteTarget(null);
      if (result.refreshed) {
        onToast("模型 Profile 已不存在，列表已刷新", "info");
      } else {
        onToast("模型 Profile 已删除", "success");
      }
    } catch {
      onToast("删除模型 Profile 失败，请重试", "error");
    } finally {
      setDeleteSubmitting(false);
    }
  }, [
    deleteSubmitting,
    deleteTarget,
    handleProfilesLoaded,
    onToast,
    profiles,
  ]);

  return (
    <section data-settings-section="model-profiles">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-xl font-semibold text-[var(--color-text-primary)]">
            模型配置
          </h2>
          <p className="mt-1 text-sm text-[var(--color-text-tertiary)]">
            管理用于生成 SQL 的 OpenAI-compatible 模型 Profile
          </p>
        </div>
        <Button type="button" size="sm" onClick={handleAdd}>
          <Plus className="h-4 w-4" aria-hidden="true" />
          添加模型
        </Button>
      </div>

      <div className="mt-6">
        {loading ? (
          <div
            role="status"
            className="rounded-lg border border-[var(--color-border)] bg-white p-6 text-center text-sm text-[var(--color-text-tertiary)] shadow-sm"
          >
            正在加载模型 Profile…
          </div>
        ) : loadFailed ? (
          <div
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 p-5"
          >
            <p className="text-sm text-red-800">无法加载模型 Profile。</p>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              className="mt-3"
              onClick={handleRetry}
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
              重试
            </Button>
          </div>
        ) : profiles.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[var(--color-border-strong)] bg-white p-8 text-center shadow-sm">
            <p className="text-sm font-medium text-[var(--color-text-secondary)]">
              还没有模型 Profile
            </p>
            <p className="mt-1 text-sm text-[var(--color-text-tertiary)]">
              添加一个模型后，即可将它设为当前模型。
            </p>
          </div>
        ) : (
          <ModelProfileList
            profiles={profiles}
            selectedId={selectedId}
            onSelect={handleSelect}
            onEdit={handleEdit}
            onDelete={setDeleteTarget}
          />
        )}
      </div>

      <div className="mt-4">
        <ModelProfileDeleteDialog
          profileName={deleteTarget?.name ?? ""}
          open={deleteTarget !== null}
          submitting={deleteSubmitting}
          onCancel={() => setDeleteTarget(null)}
          onConfirm={handleConfirmDelete}
        />
      </div>
    </section>
  );
}
