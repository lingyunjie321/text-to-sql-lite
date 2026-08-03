"use client";

import { useState, type FormEvent } from "react";

import {
  buildModelTestRequest,
  buildModelWriteRequest,
  createModelProfile,
  ProfileApiError,
  replaceModelProfile,
  testModelConnection,
  type ModelConnectionTestResponse,
  type ModelProfileFormValue,
  type ModelProfileResponse,
} from "../../lib/model-profiles";
import { Button } from "../ui/Button";
import { PasswordInput } from "./PasswordInput";
import { ToggleSwitch } from "./ToggleSwitch";

const PROFILE_ID_PATTERN = /^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$/;

type FormField =
  | "id"
  | "name"
  | "baseUrl"
  | "modelName"
  | "embeddingBaseUrl"
  | "embeddingModel"
  | "embeddingDimension";

type ModelFormErrors = Partial<Record<FormField, string>>;

export type ModelConnectionTestState =
  | { status: "untested" }
  | { status: "testing"; message: string }
  | { status: "success" | "warning" | "error"; message: string };

export interface ModelFormState {
  value: ModelProfileFormValue;
  testState: ModelConnectionTestState;
  revision: number;
}

interface ModelProfileFormProps {
  mode: "create" | "edit";
  profile?: ModelProfileResponse;
  onSaved: (profile: ModelProfileResponse) => void;
  onCancel: () => void;
}

function emptyValue(): ModelProfileFormValue {
  return {
    id: "",
    name: "",
    baseUrl: "",
    modelName: "",
    apiKey: "",
    clearApiKey: false,
    embeddingEnabled: false,
    embeddingBaseUrl: "",
    embeddingModel: "",
    embeddingDimension: "",
    embeddingApiKey: "",
    clearEmbeddingApiKey: false,
  };
}

export function createModelFormState(
  profile?: ModelProfileResponse,
): ModelFormState {
  if (!profile) {
    return {
      value: emptyValue(),
      testState: { status: "untested" },
      revision: 0,
    };
  }

  return {
    value: {
      id: profile.id,
      name: profile.name,
      baseUrl: profile.base_url,
      modelName: profile.model_name,
      apiKey: "",
      clearApiKey: false,
      embeddingEnabled: profile.embedding_base_url !== null,
      embeddingBaseUrl: profile.embedding_base_url ?? "",
      embeddingModel: profile.embedding_model ?? "",
      embeddingDimension: profile.embedding_dimension?.toString() ?? "",
      embeddingApiKey: "",
      clearEmbeddingApiKey: false,
    },
    testState: { status: "untested" },
    revision: 0,
  };
}

export function updateModelFormState(
  state: ModelFormState,
  patch: Partial<ModelProfileFormValue>,
): ModelFormState {
  const value = { ...state.value, ...patch };

  if (patch.apiKey !== undefined && patch.apiKey.trim() !== "") {
    value.clearApiKey = false;
  }
  if (patch.clearApiKey === true) value.apiKey = "";
  if (
    patch.embeddingApiKey !== undefined &&
    patch.embeddingApiKey.trim() !== ""
  ) {
    value.clearEmbeddingApiKey = false;
  }
  if (patch.clearEmbeddingApiKey === true) value.embeddingApiKey = "";

  return {
    value,
    testState: { status: "untested" },
    revision: state.revision + 1,
  };
}

export function settleModelTestState(
  state: ModelFormState,
  startedRevision: number,
  testState: ModelConnectionTestState,
): ModelFormState {
  if (state.revision !== startedRevision) return state;
  return { ...state, testState };
}

function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

export function validateModelFormValue(
  value: ModelProfileFormValue,
): ModelFormErrors {
  const errors: ModelFormErrors = {};

  if (!PROFILE_ID_PATTERN.test(value.id)) {
    errors.id =
      "Profile ID 只能包含小写字母、数字、下划线和连字符，长度不超过 64 位";
  }
  if (value.name.trim() === "") errors.name = "请输入 Profile 名称";
  if (!isHttpUrl(value.baseUrl)) {
    errors.baseUrl = "请输入有效的 HTTP 或 HTTPS 地址";
  }
  if (value.modelName.trim() === "") {
    errors.modelName = "请输入生成模型名称";
  }

  if (value.embeddingEnabled) {
    if (!isHttpUrl(value.embeddingBaseUrl)) {
      errors.embeddingBaseUrl = "请输入有效的 HTTP 或 HTTPS 地址";
    }
    if (value.embeddingModel.trim() === "") {
      errors.embeddingModel = "请输入 Embedding 模型名称";
    }
    const dimension = Number(value.embeddingDimension);
    if (
      value.embeddingDimension === "" ||
      !Number.isInteger(dimension) ||
      dimension < 1 ||
      dimension > 1_000_000
    ) {
      errors.embeddingDimension = "请输入 1 到 1000000 之间的整数";
    }
  }

  return errors;
}

export function credentialReentryMessage(
  profile: ModelProfileResponse | undefined,
  value: ModelProfileFormValue,
): string | null {
  if (!profile) return null;

  if (
    profile.generation_credential_status === "configured" &&
    value.baseUrl === profile.base_url &&
    value.apiKey.trim() === "" &&
    !value.clearApiKey
  ) {
    return "测试不会复用已保存凭据，请重新输入生成模型 API Key";
  }
  if (
    value.embeddingEnabled &&
    profile.embedding_credential_status === "configured" &&
    value.embeddingBaseUrl === profile.embedding_base_url &&
    value.embeddingApiKey.trim() === "" &&
    !value.clearEmbeddingApiKey
  ) {
    return "测试不会复用已保存凭据，请重新输入 Embedding API Key";
  }
  return null;
}

export function connectionTestState(
  response: ModelConnectionTestResponse,
): ModelConnectionTestState {
  if (response.embedding === "connected") {
    return {
      status: "success",
      message: "生成模型与 Embedding 均可用",
    };
  }
  if (response.embedding === "unavailable") {
    return {
      status: "warning",
      message: "生成模型可用，Embedding 当前不可用；可继续使用 BM25-only",
    };
  }
  return {
    status: "success",
    message: "生成模型可用，BM25-only 可用",
  };
}

export function willClearEmbedding(
  profile: ModelProfileResponse | undefined,
  value: ModelProfileFormValue,
): boolean {
  return (
    profile !== undefined &&
    profile.embedding_base_url !== null &&
    !value.embeddingEnabled
  );
}

function fieldClass(hasError: boolean): string {
  return `h-10 w-full rounded-md border bg-white px-3 text-sm text-[var(--color-text-primary)] focus:outline-none focus:ring-2 disabled:cursor-not-allowed disabled:bg-[var(--color-bg-muted)] ${
    hasError
      ? "border-red-400 focus:border-red-500 focus:ring-red-200"
      : "border-[var(--color-border-strong)] focus:border-[var(--color-primary)] focus:ring-[var(--color-primary)]/20"
  }`;
}

function publicErrorMessage(error: unknown): string {
  return error instanceof ProfileApiError
    ? error.message
    : "无法完成模型 Profile 请求，请重试";
}

export function ModelProfileForm({
  mode,
  profile,
  onSaved,
  onCancel,
}: ModelProfileFormProps) {
  const [state, setState] = useState<ModelFormState>(() =>
    createModelFormState(profile),
  );
  const [errors, setErrors] = useState<ModelFormErrors>({});
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const { value, testState } = state;
  const testing = testState.status === "testing";

  const update = (patch: Partial<ModelProfileFormValue>) => {
    setState((current) => updateModelFormState(current, patch));
    setErrors({});
    setSaveError(null);
  };

  const validate = (): boolean => {
    const nextErrors = validateModelFormValue(value);
    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const handleTest = async () => {
    if (testing || saving || !validate()) return;

    const credentialMessage = credentialReentryMessage(profile, value);
    if (credentialMessage !== null) {
      setState((current) => ({
        ...current,
        testState: { status: "error", message: credentialMessage },
      }));
      return;
    }

    const startedRevision = state.revision;
    setState((current) => ({
      ...current,
      testState: { status: "testing", message: "正在测试连接…" },
    }));
    try {
      const response = await testModelConnection(buildModelTestRequest(value));
      setState((current) =>
        settleModelTestState(
          current,
          startedRevision,
          connectionTestState(response),
        ),
      );
    } catch (error) {
      setState((current) =>
        settleModelTestState(current, startedRevision, {
          status: "error",
          message: publicErrorMessage(error),
        }),
      );
    }
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving || !validate()) return;

    setSaving(true);
    setSaveError(null);
    try {
      const request = buildModelWriteRequest(value, {
        mode,
        hadEmbedding:
          profile !== undefined && profile.embedding_base_url !== null,
      });
      const saved =
        mode === "create"
          ? await createModelProfile(request)
          : await replaceModelProfile(value.id, request);
      onSaved(saved);
    } catch (error) {
      setSaveError(publicErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const reentryHint = credentialReentryMessage(profile, value);

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-lg border border-[var(--color-border)] bg-white p-5 shadow-sm"
    >
      <div className="flex flex-col gap-1">
        <h3 className="text-lg font-semibold text-[var(--color-text-primary)]">
          {mode === "create" ? "添加模型 Profile" : "编辑模型 Profile"}
        </h3>
        <p className="text-sm text-[var(--color-text-tertiary)]">
          配置一个用于 SQL 生成的 OpenAI-compatible 模型。
        </p>
      </div>

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <label className="block text-sm text-[var(--color-text-secondary)]">
          <span className="mb-1.5 block font-medium">Profile ID</span>
          <input
            name="id"
            readOnly={mode === "edit"}
            value={value.id}
            onChange={(event) => update({ id: event.target.value })}
            className={fieldClass(Boolean(errors.id))}
            aria-invalid={Boolean(errors.id)}
          />
          {errors.id ? (
            <span className="mt-1 block text-xs text-red-700">{errors.id}</span>
          ) : null}
        </label>

        <label className="block text-sm text-[var(--color-text-secondary)]">
          <span className="mb-1.5 block font-medium">名称</span>
          <input
            name="name"
            value={value.name}
            onChange={(event) => update({ name: event.target.value })}
            className={fieldClass(Boolean(errors.name))}
            aria-invalid={Boolean(errors.name)}
          />
          {errors.name ? (
            <span className="mt-1 block text-xs text-red-700">{errors.name}</span>
          ) : null}
        </label>

        <label className="block text-sm text-[var(--color-text-secondary)] sm:col-span-2">
          <span className="mb-1.5 block font-medium">Provider 类型</span>
          <input
            name="providerType"
            readOnly
            value="openai_compatible"
            className={fieldClass(false)}
          />
        </label>

        <label className="block text-sm text-[var(--color-text-secondary)] sm:col-span-2">
          <span className="mb-1.5 block font-medium">生成模型 Base URL</span>
          <input
            name="baseUrl"
            type="url"
            value={value.baseUrl}
            onChange={(event) => update({ baseUrl: event.target.value })}
            placeholder="http://localhost:11434/v1"
            className={fieldClass(Boolean(errors.baseUrl))}
            aria-invalid={Boolean(errors.baseUrl)}
          />
          {errors.baseUrl ? (
            <span className="mt-1 block text-xs text-red-700">
              {errors.baseUrl}
            </span>
          ) : null}
        </label>

        <label className="block text-sm text-[var(--color-text-secondary)]">
          <span className="mb-1.5 block font-medium">生成模型名称</span>
          <input
            name="modelName"
            value={value.modelName}
            onChange={(event) => update({ modelName: event.target.value })}
            className={fieldClass(Boolean(errors.modelName))}
            aria-invalid={Boolean(errors.modelName)}
          />
          {errors.modelName ? (
            <span className="mt-1 block text-xs text-red-700">
              {errors.modelName}
            </span>
          ) : null}
        </label>

        <div className="text-sm text-[var(--color-text-secondary)]">
          <label htmlFor="model-api-key" className="mb-1.5 block font-medium">
            生成模型 API Key（可选）
          </label>
          <PasswordInput
            id="model-api-key"
            value={value.apiKey}
            onChange={(apiKey) => update({ apiKey })}
            autoComplete="new-password"
          />
          {mode === "edit" ? (
            <p className="mt-1 text-xs text-[var(--color-text-tertiary)]">
              留空则保留当前凭据
            </p>
          ) : null}
          {mode === "edit" ? (
            <label className="mt-2 flex items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={value.clearApiKey}
                onChange={(event) =>
                  update({ clearApiKey: event.target.checked })
                }
              />
              清除已保存凭据
            </label>
          ) : null}
        </div>
      </div>

      <div className="mt-5 rounded-lg border border-[var(--color-border)] p-4">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h4 className="text-sm font-medium text-[var(--color-text-primary)]">
              Embedding（可选增强）
            </h4>
            <p className="mt-0.5 text-xs text-[var(--color-text-tertiary)]">
              未开启时使用 BM25-only。
            </p>
          </div>
          <ToggleSwitch
            checked={value.embeddingEnabled}
            onChange={(embeddingEnabled) => update({ embeddingEnabled })}
            ariaLabel="启用 Embedding"
          />
        </div>

        {willClearEmbedding(profile, value) ? (
          <p role="alert" className="mt-3 text-sm text-amber-700">
            保存后会清除 Embedding 配置和凭据
          </p>
        ) : null}

        {value.embeddingEnabled ? (
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <label className="block text-sm text-[var(--color-text-secondary)] sm:col-span-2">
              <span className="mb-1.5 block font-medium">
                Embedding Base URL
              </span>
              <input
                name="embeddingBaseUrl"
                type="url"
                value={value.embeddingBaseUrl}
                onChange={(event) =>
                  update({ embeddingBaseUrl: event.target.value })
                }
                className={fieldClass(Boolean(errors.embeddingBaseUrl))}
                aria-invalid={Boolean(errors.embeddingBaseUrl)}
              />
              {errors.embeddingBaseUrl ? (
                <span className="mt-1 block text-xs text-red-700">
                  {errors.embeddingBaseUrl}
                </span>
              ) : null}
            </label>

            <label className="block text-sm text-[var(--color-text-secondary)]">
              <span className="mb-1.5 block font-medium">
                Embedding 模型名称
              </span>
              <input
                name="embeddingModel"
                value={value.embeddingModel}
                onChange={(event) =>
                  update({ embeddingModel: event.target.value })
                }
                className={fieldClass(Boolean(errors.embeddingModel))}
                aria-invalid={Boolean(errors.embeddingModel)}
              />
              {errors.embeddingModel ? (
                <span className="mt-1 block text-xs text-red-700">
                  {errors.embeddingModel}
                </span>
              ) : null}
            </label>

            <label className="block text-sm text-[var(--color-text-secondary)]">
              <span className="mb-1.5 block font-medium">向量维数</span>
              <input
                name="embeddingDimension"
                type="number"
                min={1}
                max={1_000_000}
                step={1}
                value={value.embeddingDimension}
                onChange={(event) =>
                  update({ embeddingDimension: event.target.value })
                }
                className={fieldClass(Boolean(errors.embeddingDimension))}
                aria-invalid={Boolean(errors.embeddingDimension)}
              />
              {errors.embeddingDimension ? (
                <span className="mt-1 block text-xs text-red-700">
                  {errors.embeddingDimension}
                </span>
              ) : null}
            </label>

            <div className="text-sm text-[var(--color-text-secondary)] sm:col-span-2">
              <label
                htmlFor="embedding-api-key"
                className="mb-1.5 block font-medium"
              >
                Embedding API Key（可选）
              </label>
              <PasswordInput
                id="embedding-api-key"
                value={value.embeddingApiKey}
                onChange={(embeddingApiKey) => update({ embeddingApiKey })}
                autoComplete="new-password"
              />
              {mode === "edit" ? (
                <p className="mt-1 text-xs text-[var(--color-text-tertiary)]">
                  留空则保留当前凭据
                </p>
              ) : null}
              {mode === "edit" ? (
                <label className="mt-2 flex items-center gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={value.clearEmbeddingApiKey}
                    onChange={(event) =>
                      update({ clearEmbeddingApiKey: event.target.checked })
                    }
                  />
                  清除已保存凭据
                </label>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>

      <div className="mt-5 rounded-md bg-[var(--color-bg-subtle)] p-3 text-sm">
        <p
          role={testState.status === "error" ? "alert" : "status"}
          className={
            testState.status === "error"
              ? "text-red-700"
              : testState.status === "warning"
                ? "text-amber-700"
                : "text-[var(--color-text-secondary)]"
          }
        >
          {testState.status === "untested" ? "连接状态：未测试" : testState.message}
        </p>
        {reentryHint !== null && testState.status !== "error" ? (
          <p className="mt-1 text-xs text-amber-700">{reentryHint}</p>
        ) : null}
      </div>

      {saveError ? (
        <p role="alert" className="mt-4 text-sm text-red-700">
          {saveError}
        </p>
      ) : null}

      <div className="mt-5 flex flex-wrap justify-end gap-2">
        <Button
          type="button"
          variant="secondary"
          onClick={onCancel}
          disabled={saving || testing}
        >
          取消
        </Button>
        <Button
          type="button"
          variant="secondary"
          onClick={() => void handleTest()}
          loading={testing}
          disabled={saving}
        >
          测试连接
        </Button>
        <Button type="submit" loading={saving} disabled={testing}>
          保存 Profile
        </Button>
      </div>
    </form>
  );
}
