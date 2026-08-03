import type { ModelProfileResponse } from "../../lib/model-profiles";

export interface ModelProfileState {
  profiles: ModelProfileResponse[];
  selectedId: string | null;
  profileCount: number;
}

interface LoadModelProfileDependencies {
  removeLegacyConfig: () => void;
  listProfiles: () => Promise<ModelProfileResponse[]>;
  reconcileSelectedId: (profileIds: readonly string[]) => string | null;
}

interface DeleteModelProfileDependencies {
  deleteProfile: (profileId: string) => Promise<void>;
  listProfiles: () => Promise<ModelProfileResponse[]>;
  getSelectedId: () => string | null;
  clearSelectedId: () => void;
  reconcileSelectedId: (profileIds: readonly string[]) => string | null;
  isMissingError: (error: unknown) => boolean;
}

export interface DeleteModelProfileResult extends ModelProfileState {
  refreshed: boolean;
}

function stateFromProfiles(
  profiles: ModelProfileResponse[],
  selectedId: string | null,
): ModelProfileState {
  return {
    profiles,
    selectedId,
    profileCount: profiles.length,
  };
}

export async function loadModelProfileState(
  dependencies: LoadModelProfileDependencies,
): Promise<ModelProfileState> {
  dependencies.removeLegacyConfig();
  const profiles = await dependencies.listProfiles();
  const selectedId = dependencies.reconcileSelectedId(
    profiles.map((profile) => profile.id),
  );
  return stateFromProfiles(profiles, selectedId);
}

export async function deleteModelProfileFromState(
  profiles: readonly ModelProfileResponse[],
  profileId: string,
  dependencies: DeleteModelProfileDependencies,
): Promise<DeleteModelProfileResult> {
  try {
    await dependencies.deleteProfile(profileId);
  } catch (error) {
    if (!dependencies.isMissingError(error)) throw error;

    const refreshedProfiles = await dependencies.listProfiles();
    const selectedId = dependencies.reconcileSelectedId(
      refreshedProfiles.map((profile) => profile.id),
    );
    return {
      ...stateFromProfiles(refreshedProfiles, selectedId),
      refreshed: true,
    };
  }

  const nextProfiles = profiles.filter((profile) => profile.id !== profileId);
  let selectedId = dependencies.getSelectedId();
  if (selectedId === profileId) {
    dependencies.clearSelectedId();
    selectedId = null;
  }
  return {
    ...stateFromProfiles(nextProfiles, selectedId),
    refreshed: false,
  };
}

export function modelProfileCountStatus(
  profileCount: number | null | undefined,
): "加载中" | "不可用" | "未配置" | "已配置" {
  if (profileCount === undefined) return "加载中";
  if (profileCount === null) return "不可用";
  return profileCount > 0 ? "已配置" : "未配置";
}

export function renderActiveSection<SectionId, Content>(
  activeSection: SectionId,
  renderSection: (section: SectionId) => Content,
): Content {
  return renderSection(activeSection);
}
