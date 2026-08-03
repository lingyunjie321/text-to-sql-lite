import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ModelProfileDeleteDialog } from "./ModelProfileDeleteDialog";
import { ModelProfileList } from "./ModelProfileList";
import type { ModelProfileResponse } from "../../lib/model-profiles";

const profiles: ModelProfileResponse[] = [
  {
    id: "local-model",
    name: "本地 Qwen",
    provider_type: "openai_compatible",
    base_url: "http://localhost:11434/v1",
    model_name: "qwen2.5-coder",
    embedding_base_url: null,
    embedding_model: null,
    embedding_dimension: null,
    generation_credential_status: "configured",
    embedding_credential_status: "not_applicable",
  },
  {
    id: "remote-model",
    name: "远程模型",
    provider_type: "openai_compatible",
    base_url: "https://models.example.test/v1",
    model_name: "sql-model",
    embedding_base_url: "https://embedding.example.test/v1",
    embedding_model: "embedding-model",
    embedding_dimension: 1024,
    generation_credential_status: "missing",
    embedding_credential_status: "missing",
  },
];

describe("ModelProfileList", () => {
  it("labels the selected profile and describes credential presence without claiming a connection succeeded", () => {
    const markup = renderToStaticMarkup(
      <ModelProfileList
        profiles={profiles}
        selectedId="local-model"
        onSelect={() => undefined}
        onEdit={() => undefined}
        onDelete={() => undefined}
      />,
    );

    expect(markup).toContain("本地 Qwen");
    expect(markup).toContain("qwen2.5-coder");
    expect(markup).toContain("当前模型");
    expect(markup).toContain("生成凭据：已配置");
    expect(markup).toContain("生成凭据：缺失");
    expect(markup).toContain("Embedding 未配置");
    expect(markup).toContain("Embedding 已配置 · 凭据：缺失");
    expect(markup).not.toContain("连接成功");
    expect(markup).not.toContain("http://localhost:11434/v1");
    expect(markup).not.toContain("https://models.example.test/v1");
  });
});

describe("ModelProfileDeleteDialog", () => {
  it("shows only the profile name and disables both choices while deletion is submitting", () => {
    const markup = renderToStaticMarkup(
      <ModelProfileDeleteDialog
        profileName="远程模型"
        open
        submitting
        onCancel={() => undefined}
        onConfirm={async () => undefined}
      />,
    );

    expect(markup).toContain("远程模型");
    expect(markup).toContain("确认删除");
    expect(markup).not.toContain("models.example.test");
    expect(markup.match(/disabled=""/g)).toHaveLength(2);
  });
});
