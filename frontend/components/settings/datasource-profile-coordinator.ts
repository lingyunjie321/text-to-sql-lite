import type { DatasourceProfileResponse } from "@/lib/datasource-profiles";

interface DeleteDependencies {
  deleteProfile: (profileId: string) => Promise<void>;
  getSelectedId: () => string | null;
  clearSelectedId: () => void;
}

export async function deleteDatasourceProfileFromState(
  profiles: readonly DatasourceProfileResponse[],
  profileId: string,
  dependencies: DeleteDependencies,
): Promise<{ profiles: DatasourceProfileResponse[]; selectedId: string | null }> {
  await dependencies.deleteProfile(profileId);
  const nextProfiles = profiles.filter((profile) => profile.id !== profileId);
  const selectedId = dependencies.getSelectedId();
  if (selectedId === profileId) {
    dependencies.clearSelectedId();
    return { profiles: nextProfiles, selectedId: null };
  }
  return { profiles: nextProfiles, selectedId };
}
