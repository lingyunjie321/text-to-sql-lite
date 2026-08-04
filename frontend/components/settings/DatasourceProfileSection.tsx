"use client";

import { Plus, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import {
  deleteDatasourceProfile,
  listDatasourceProfiles,
  type DatasourceProfileResponse,
} from "@/lib/datasource-profiles";
import {
  clearSelectedDatasourceProfileId,
  getSelectedDatasourceProfileId,
  reconcileSelectedDatasourceProfileId,
  removeLegacyDatasourceConfig,
  setSelectedDatasourceProfileId,
} from "@/lib/profile-selection";
import { DatasourceProfileForm } from "./DatasourceProfileForm";
import { DatasourceProfileList } from "./DatasourceProfileList";
import { deleteDatasourceProfileFromState } from "./datasource-profile-coordinator";

interface Props {
  onToast: (message: string, type?: "success" | "info" | "error") => void;
  onProfileCountChange: (count: number | null) => void;
}

export function DatasourceProfileSection({ onToast, onProfileCountChange }: Props) {
  const [profiles, setProfiles] = useState<DatasourceProfileResponse[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [formTarget, setFormTarget] = useState<"create" | DatasourceProfileResponse | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const handleLoaded = useCallback((nextProfiles: DatasourceProfileResponse[]) => {
    const current = reconcileSelectedDatasourceProfileId(nextProfiles.map((item) => item.id));
    setProfiles(nextProfiles);
    setSelectedId(current);
    setLoadFailed(false);
    setLoading(false);
    onProfileCountChange(nextProfiles.length);
  }, [onProfileCountChange]);

  const handleLoadFailed = useCallback(() => {
    setLoadFailed(true);
    setLoading(false);
    onProfileCountChange(null);
  }, [onProfileCountChange]);

  const load = useCallback(() => {
    removeLegacyDatasourceConfig();
    return listDatasourceProfiles().then(handleLoaded, handleLoadFailed);
  }, [handleLoadFailed, handleLoaded]);

  useEffect(() => {
    removeLegacyDatasourceConfig();
    let active = true;
    listDatasourceProfiles().then(
      (nextProfiles) => {
        if (active) handleLoaded(nextProfiles);
      },
      () => {
        if (active) handleLoadFailed();
      },
    );
    return () => {
      active = false;
    };
  }, [handleLoadFailed, handleLoaded]);

  const handleSaved = (saved: DatasourceProfileResponse) => {
    const index = profiles.findIndex((item) => item.id === saved.id);
    const next = index === -1
      ? [...profiles, saved]
      : profiles.map((item) => (item.id === saved.id ? saved : item));
    setProfiles(next);
    onProfileCountChange(next.length);
    setFormTarget(null);
    onToast(formTarget === "create" ? "数据源 Profile 已添加" : "数据源 Profile 已更新", "success");
  };

  const handleDelete = async (profile: DatasourceProfileResponse) => {
    if (!window.confirm(`确定删除数据源“${profile.name}”吗？`)) return;
    setDeletingId(profile.id);
    try {
      const result = await deleteDatasourceProfileFromState(profiles, profile.id, {
        deleteProfile: deleteDatasourceProfile,
        getSelectedId: getSelectedDatasourceProfileId,
        clearSelectedId: clearSelectedDatasourceProfileId,
      });
      setProfiles(result.profiles);
      setSelectedId(result.selectedId);
      onProfileCountChange(result.profiles.length);
      onToast("数据源 Profile 已删除", "success");
    } catch {
      onToast("删除数据源 Profile 失败，请重试", "error");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <section data-settings-section="datasource-profiles">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-xl font-semibold text-[var(--color-text-primary)]">数据库配置</h2>
          <p className="mt-1 text-sm text-[var(--color-text-tertiary)]">
            管理 PostgreSQL 或 MySQL 数据源，并明确选择允许查询的表。
          </p>
        </div>
        <Button type="button" size="sm" disabled={loading || loadFailed || formTarget !== null || deletingId !== null} onClick={() => setFormTarget("create")}>
          <Plus className="h-4 w-4" aria-hidden="true" />
          添加数据源
        </Button>
      </div>

      {formTarget !== null ? (
        <div className="mt-6">
          <DatasourceProfileForm
            key={formTarget === "create" ? "create" : formTarget.id}
            mode={formTarget === "create" ? "create" : "edit"}
            profile={formTarget === "create" ? undefined : formTarget}
            onSaved={handleSaved}
            onCancel={() => setFormTarget(null)}
          />
        </div>
      ) : null}

      {formTarget === null ? (
        <div className="mt-6">
          {loading ? (
            <div role="status" className="rounded-lg border border-[var(--color-border)] bg-white p-6 text-center text-sm text-[var(--color-text-tertiary)]">
              正在加载数据源 Profile…
            </div>
          ) : loadFailed ? (
            <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-5">
              <p className="text-sm text-red-800">无法加载数据源 Profile。</p>
              <Button type="button" variant="secondary" size="sm" className="mt-3" onClick={() => { setLoading(true); void load(); }}>
                <RefreshCw className="h-3.5 w-3.5" />重试
              </Button>
            </div>
          ) : profiles.length === 0 ? (
            <div className="rounded-lg border border-dashed border-[var(--color-border-strong)] bg-white p-8 text-center shadow-sm">
              <p className="text-sm font-medium text-[var(--color-text-secondary)]">还没有数据源 Profile</p>
              <p className="mt-1 text-sm text-[var(--color-text-tertiary)]">添加、测试连接并选择授权表后，即可设为当前数据源。</p>
            </div>
          ) : (
            <DatasourceProfileList
              profiles={profiles}
              selectedId={selectedId}
              onSelect={(profileId) => {
                setSelectedDatasourceProfileId(profileId);
                setSelectedId(profileId);
                onToast("已设为当前数据源", "success");
              }}
              onEdit={setFormTarget}
              onDelete={(profile) => void handleDelete(profile)}
            />
          )}
        </div>
      ) : null}
    </section>
  );
}
