"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { WelcomeSection } from "./WelcomeSection";
import { ConversationFlow, type ConversationTurn } from "./ConversationFlow";
import { InputDock } from "./InputDock";
import { queryTextToSql } from "@/lib/api";
import { saveRecord } from "@/lib/history";
import { getDbConfig, isDbConfigured } from "@/lib/datasource-config";
import type {
  QueryRequest,
  QueryResponse,
  DatasourceOverride,
  StoredDbConfig,
} from "@/lib/types";

export function buildWorkbenchQueryRequest(
  question: string,
  storedDbConfig: StoredDbConfig,
): QueryRequest {
  let datasourceOverride: DatasourceOverride | undefined;
  let datasourceId = "pagila";
  if (isDbConfigured(storedDbConfig)) {
    datasourceId = storedDbConfig.datasource_id || "pagila";
    if (storedDbConfig.connection.mode === "form") {
      datasourceOverride = {
        host: storedDbConfig.connection.host || "",
        port: storedDbConfig.connection.port || 0,
        database: storedDbConfig.connection.database || "",
        username: storedDbConfig.connection.username || "",
        password: storedDbConfig.connection.password || "",
        type: storedDbConfig.type,
        schemas: storedDbConfig.auth.schemas,
        allowed_tables: storedDbConfig.auth.allowed_tables,
      };
    }
  }

  return {
    question,
    datasource_id: datasourceId,
    debug: false,
    ...(datasourceOverride && { datasource_override: datasourceOverride }),
  };
}

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
        const storedDbConfig = getDbConfig();
        const response = await queryTextToSql(
          buildWorkbenchQueryRequest(trimmed, storedDbConfig),
        );

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
