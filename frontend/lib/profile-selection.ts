export const SELECTED_MODEL_PROFILE_KEY = "text-to-sql-selected-model-profile-id";
export const LEGACY_MODEL_CONFIG_KEY = "text-to-sql-model-config";

const PROFILE_ID_PATTERN = /^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$/;

function getBrowserStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  return window.localStorage;
}

function isValidProfileId(value: string): boolean {
  return PROFILE_ID_PATTERN.test(value);
}

export function getSelectedModelProfileId(): string | null {
  const storage = getBrowserStorage();
  if (!storage) return null;

  const profileId = storage.getItem(SELECTED_MODEL_PROFILE_KEY);
  if (profileId === null || isValidProfileId(profileId)) return profileId;

  storage.removeItem(SELECTED_MODEL_PROFILE_KEY);
  return null;
}

export function setSelectedModelProfileId(profileId: string): void {
  if (!isValidProfileId(profileId)) {
    throw new Error("Model profile ID is invalid.");
  }

  getBrowserStorage()?.setItem(SELECTED_MODEL_PROFILE_KEY, profileId);
}

export function clearSelectedModelProfileId(): void {
  getBrowserStorage()?.removeItem(SELECTED_MODEL_PROFILE_KEY);
}

export function reconcileSelectedModelProfileId(profileIds: readonly string[]): string | null {
  const profileId = getSelectedModelProfileId();
  if (profileId === null || profileIds.includes(profileId)) return profileId;

  clearSelectedModelProfileId();
  return null;
}

export function removeLegacyModelConfig(): void {
  getBrowserStorage()?.removeItem(LEGACY_MODEL_CONFIG_KEY);
}
