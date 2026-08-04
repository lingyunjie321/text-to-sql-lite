"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { WelcomeSection } from "./WelcomeSection";
import { ConversationFlow, type ConversationTurn } from "./ConversationFlow";
import { InputDock } from "./InputDock";
import { queryTextToSql } from "@/lib/api";
import { saveRecord } from "@/lib/history";
import { listDatasourceProfiles } from "@/lib/datasource-profiles";
import { listModelProfiles } from "@/lib/model-profiles";
import {
  clearSelectedDatasourceProfileId,
  clearSelectedModelProfileId,
  getSelectedDatasourceProfileId,
  getSelectedModelProfileId,
  removeLegacyDatasourceConfig,
} from "@/lib/profile-selection";
import type { QueryRequest, QueryResponse } from "@/lib/types";

export function buildWorkbenchQueryRequest(
  question: string,
  datasourceId: string,
  modelProfileId: string,
): QueryRequest {
  return {
    question,
    datasource_id: datasourceId,
    model_profile_id: modelProfileId,
    debug: false,
  };
}

interface WorkbenchProfileDependencies {
  getModelId: () => string | null;
  getDatasourceId: () => string | null;
  listModelIds: () => Promise<string[]>;
  listDatasourceIds: () => Promise<string[]>;
  clearModelId: () => void;
  clearDatasourceId: () => void;
}

type WorkbenchProfileSelection =
  | { ok: true; modelProfileId: string; datasourceId: string }
  | { ok: false; message: string };

export async function resolveWorkbenchProfileSelection(
  dependencies: WorkbenchProfileDependencies,
): Promise<WorkbenchProfileSelection> {
  const modelProfileId = dependencies.getModelId();
  const datasourceId = dependencies.getDatasourceId();
  if (!modelProfileId || !datasourceId) {
    return {
      ok: false,
      message: "请先在设置页配置并选择当前模型和数据源。",
    };
  }

  const [modelIds, datasourceIds] = await Promise.all([
    dependencies.listModelIds(),
    dependencies.listDatasourceIds(),
  ]);
  const modelExists = modelIds.includes(modelProfileId);
  const datasourceExists = datasourceIds.includes(datasourceId);
  if (!modelExists) dependencies.clearModelId();
  if (!datasourceExists) dependencies.clearDatasourceId();
  if (!modelExists || !datasourceExists) {
    return {
      ok: false,
      message: "当前模型或数据源已不存在，请在设置页重新选择。",
    };
  }
  return { ok: true, modelProfileId, datasourceId };
}

const profileDependencies: WorkbenchProfileDependencies = {
  getModelId: getSelectedModelProfileId,
  getDatasourceId: getSelectedDatasourceProfileId,
  listModelIds: async () => (await listModelProfiles()).map((profile) => profile.id),
  listDatasourceIds: async () =>
    (await listDatasourceProfiles()).map((profile) => profile.id),
  clearModelId: clearSelectedModelProfileId,
  clearDatasourceId: clearSelectedDatasourceProfileId,
};

export function Workbench() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [selectionMessage, setSelectionMessage] = useState<string | null>(null);
  const conversationIdRef = useRef<string | null>(null);

  useEffect(() => {
    removeLegacyDatasourceConfig();
  }, []);

  const submitQuestion = useCallback(
    async (
      question: string,
      options?: {
        isSupplement?: boolean;
        turnId?: string;
      },
    ) => {
      const trimmed = question.trim();
      if (!trimmed || isLoading) return;

      setIsLoading(true);
      let selection: WorkbenchProfileSelection;
      try {
        selection = await resolveWorkbenchProfileSelection(profileDependencies);
      } catch {
        setSelectionMessage("无法读取当前模型和数据源，请确认后端已启动后重试。");
        setIsLoading(false);
        return;
      }
      if (!selection.ok) {
        setSelectionMessage(selection.message);
        setIsLoading(false);
        return;
      }
      setSelectionMessage(null);

      const turnId = options?.turnId || `turn-${Date.now()}`;
      const isSupplement = options?.isSupplement ?? false;
      const conversationId =
        conversationIdRef.current ?? `conv-${Date.now()}`;
      conversationIdRef.current = conversationId;

      // Add user message + loading turn
      setTurns((prev) => [
        ...prev,
        {
          id: turnId,
          question: trimmed,
          isSupplement,
          response: null,
          isLoading: true,
        },
      ]);

      setInputValue("");

      try {
        const response = await queryTextToSql(
          buildWorkbenchQueryRequest(
            trimmed,
            selection.datasourceId,
            selection.modelProfileId,
          ),
        );

        // Update the turn with the response
        setTurns((prev) =>
          prev.map((t) =>
            t.id === turnId
              ? { ...t, response, isLoading: false }
              : t,
          ),
        );

        // Keep non-sensitive query history only for this browser session.
        saveRecord(conversationId, trimmed, response);
      } catch {
        // Network error — construct a FAILED_INTERNAL response
        const errorResponse: QueryResponse = {
          request_id: "unknown",
          trace_id: "unknown",
          status: "FAILED_INTERNAL",
          error: {
            error_type: "CONNECTION_ERROR",
            code: "NETWORK_ERROR",
            message: "网络连接失败，请检查网络后重试。",
          },
        };

        setTurns((prev) =>
          prev.map((t) =>
            t.id === turnId
              ? { ...t, response: errorResponse, isLoading: false }
              : t,
          ),
        );

        saveRecord(
          conversationId,
          trimmed,
          errorResponse,
        );
      } finally {
        setIsLoading(false);
      }
    },
    [isLoading],
  );

  // Handle URL params (?q= for sample questions, ?conversation= for history restore)
  useEffect(() => {
    const q = searchParams.get("q");
    if (!q) return;
    const decoded = decodeURIComponent(q);
    router.replace("/");
    const timer = window.setTimeout(() => submitQuestion(decoded), 100);
    return () => window.clearTimeout(timer);
    // This runs only for a URL-provided question; submit state must not retrigger it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router, searchParams]);

  const handleSubmit = useCallback(() => {
    submitQuestion(inputValue);
  }, [inputValue, submitQuestion]);

  const handleSampleClick = useCallback(
    (question: string) => {
      submitQuestion(question);
    },
    [submitQuestion],
  );

  const handleClarificationSubmit = useCallback(
    (turnId: string, supplement: string) => {
      // Find the original question
      const turn = turns.find((t) => t.id === turnId);
      if (!turn) return;

      // Build combined question
      const combinedQuestion = `${turn.question}\n\n补充说明：${supplement}`;
      submitQuestion(combinedQuestion, { isSupplement: true });
    },
    [turns, submitQuestion],
  );

  const handleClarificationSkip = useCallback(() => {
    // The clarification card stays in the conversation as history.
  }, []);

  const handleRetry = useCallback(
    (turnId: string) => {
      const turn = turns.find((t) => t.id === turnId);
      if (!turn) return;
      submitQuestion(turn.question);
    },
    [turns, submitQuestion],
  );

  const handleModifyQuestion = useCallback(
    (question: string) => {
      setInputValue(question);
      // Focus the textarea (it will auto-focus since we set the value)
    },
    [],
  );

  const hasTurns = turns.length > 0;

  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 pb-32 md:px-6 md:pb-8">
      {!hasTurns && !isLoading && (
        <WelcomeSection onSampleClick={handleSampleClick} />
      )}

      {hasTurns && (
        <div className="py-4">
          <ConversationFlow
            turns={turns}
            onClarificationSubmit={handleClarificationSubmit}
            onClarificationSkip={handleClarificationSkip}
            onRetry={handleRetry}
            onModifyQuestion={handleModifyQuestion}
          />
        </div>
      )}

      {selectionMessage ? (
        <div
          role="alert"
          className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
        >
          {selectionMessage} 请前往
          <button
            type="button"
            className="mx-1 font-medium text-[var(--color-primary)] underline"
            onClick={() => router.push("/settings")}
          >
            设置页
          </button>
          完成配置。
        </div>
      ) : null}

      <InputDock
        value={inputValue}
        onChange={setInputValue}
        onSubmit={handleSubmit}
        isLoading={isLoading}
      />
    </div>
  );
}
