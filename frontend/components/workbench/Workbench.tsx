"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { WelcomeSection } from "./WelcomeSection";
import { ConversationFlow, type ConversationTurn } from "./ConversationFlow";
import { InputDock } from "./InputDock";
import { queryTextToSql } from "@/lib/api";
import { saveRecord } from "@/lib/history";
import { getModelConfig, isModelConfigured } from "@/lib/model-config";
import { getDbConfig, isDbConfigured } from "@/lib/datasource-config";
import type {
  QueryResponse,
  RequestModelConfig,
  RequestDatasourceConfig,
  ModelEndpoint,
} from "@/lib/types";

export function Workbench() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const conversationIdRef = useRef<string>(
    `conv-${Date.now()}`,
  );

  // Handle URL params (?q= for sample questions, ?conversation= for history restore)
  useEffect(() => {
    const q = searchParams.get("q");
    if (q) {
      // Decode and fill input, then auto-submit
      const decoded = decodeURIComponent(q);
      setInputValue(decoded);
      // Clear the URL param
      router.replace("/");
      // Auto-submit after a brief delay to let state settle
      setTimeout(() => {
        submitQuestion(decoded);
      }, 100);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

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

      const turnId = options?.turnId || `turn-${Date.now()}`;
      const isSupplement = options?.isSupplement ?? false;

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

      setIsLoading(true);
      setInputValue("");

      try {
        // 读取前端配置（存 localStorage，⚠️ 需后端扩展才能生效）
        const storedModelConfig = getModelConfig();
        const storedDbConfig = getDbConfig();

        // 转换模型配置：只传 enabled 的模型
        let modelConfig: RequestModelConfig | undefined;
        if (isModelConfigured(storedModelConfig)) {
          const pickEnabled = (ep: ModelEndpoint): ModelEndpoint | undefined =>
            ep.enabled ? ep : undefined;
          const mc: RequestModelConfig = {};
          const simple = pickEnabled(storedModelConfig.models.simple);
          const standard = pickEnabled(storedModelConfig.models.standard);
          const complex = pickEnabled(storedModelConfig.models.complex);
          const fallback = pickEnabled(storedModelConfig.models.fallback);
          if (simple) mc.simple = simple;
          if (standard) mc.standard = standard;
          if (complex) mc.complex = complex;
          if (fallback) mc.fallback = fallback;
          if (Object.keys(mc).length > 0) modelConfig = mc;
        }

        // 转换数据源配置：表单模式才传结构化字段
        let datasourceConfig: RequestDatasourceConfig | undefined;
        let datasourceId = "pagila";
        if (isDbConfigured(storedDbConfig)) {
          datasourceId = storedDbConfig.datasource_id || "pagila";
          if (storedDbConfig.connection.mode === "form") {
            datasourceConfig = {
              datasource_id: storedDbConfig.datasource_id,
              type: storedDbConfig.type,
              host: storedDbConfig.connection.host || "",
              port: storedDbConfig.connection.port || 0,
              database: storedDbConfig.connection.database || "",
              username: storedDbConfig.connection.username || "",
              password: storedDbConfig.connection.password || "",
              schemas: storedDbConfig.auth.schemas,
              allowed_tables: storedDbConfig.auth.allowed_tables,
            };
          }
        }

        const response = await queryTextToSql({
          question: trimmed,
          datasource_id: datasourceId,
          debug: false,
          ...(modelConfig && { model_config: modelConfig }),
          ...(datasourceConfig && { datasource_config: datasourceConfig }),
        });

        // Update the turn with the response
        setTurns((prev) =>
          prev.map((t) =>
            t.id === turnId
              ? { ...t, response, isLoading: false }
              : t,
          ),
        );

        // Save to localStorage
        saveRecord(conversationIdRef.current, trimmed, response);
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
          conversationIdRef.current,
          trimmed,
          errorResponse,
        );
      } finally {
        setIsLoading(false);
      }
    },
    [isLoading],
  );

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

  const handleClarificationSkip = useCallback(
    (turnId: string) => {
      // Mark the turn as skipped (just leave it as is, user can continue)
      // The clarification card stays in the conversation as history
    },
    [],
  );

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

      <InputDock
        value={inputValue}
        onChange={setInputValue}
        onSubmit={handleSubmit}
        isLoading={isLoading}
      />
    </div>
  );
}
