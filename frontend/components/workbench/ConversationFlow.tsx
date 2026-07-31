"use client";

import { useEffect, useRef } from "react";
import { Loader2 } from "lucide-react";
import { UserMessage } from "./UserMessage";
import { QueryResultCard } from "./QueryResultCard";
import { ClarificationCard } from "./ClarificationCard";
import { ErrorCard } from "./ErrorCard";
import { TableSkeleton } from "@/components/ui/Skeleton";
import type { QueryResponse } from "@/lib/types";

export interface ConversationTurn {
  id: string;
  question: string;
  isSupplement?: boolean;
  response: QueryResponse | null;
  isLoading: boolean;
}

interface ConversationFlowProps {
  turns: ConversationTurn[];
  onClarificationSubmit: (turnId: string, supplement: string) => void;
  onClarificationSkip: (turnId: string) => void;
  onRetry: (turnId: string) => void;
  onModifyQuestion: (question: string) => void;
}

export function ConversationFlow({
  turns,
  onClarificationSubmit,
  onClarificationSkip,
  onRetry,
  onModifyQuestion,
}: ConversationFlowProps) {
  const endRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when turns change
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  return (
    <div className="space-y-4">
      {turns.map((turn) => (
        <div key={turn.id} className="space-y-3">
          {/* User message */}
          <UserMessage
            text={turn.question}
            isSupplement={turn.isSupplement}
          />

          {/* Response */}
          {turn.isLoading && <LoadingCard />}
          {turn.response && !turn.isLoading && (
            <ResponseCard
              turn={turn}
              onClarificationSubmit={onClarificationSubmit}
              onClarificationSkip={onClarificationSkip}
              onRetry={onRetry}
              onModifyQuestion={onModifyQuestion}
            />
          )}
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}

function LoadingCard() {
  return (
    <div className="animate-fade-in rounded-lg border border-[var(--color-border)] bg-white p-4 shadow-sm">
      <div className="flex items-center gap-2 text-sm text-[var(--color-text-secondary)]">
        <Loader2 className="h-4 w-4 animate-spin text-[var(--color-primary)]" />
        <span>正在理解你的问题...</span>
      </div>
      <div className="mt-4">
        <TableSkeleton />
      </div>
    </div>
  );
}

function ResponseCard({
  turn,
  onClarificationSubmit,
  onClarificationSkip,
  onRetry,
  onModifyQuestion,
}: {
  turn: ConversationTurn;
  onClarificationSubmit: (turnId: string, supplement: string) => void;
  onClarificationSkip: (turnId: string) => void;
  onRetry: (turnId: string) => void;
  onModifyQuestion: (question: string) => void;
}) {
  const response = turn.response!;

  if (response.status === "CLARIFICATION_REQUIRED") {
    return (
      <ClarificationCard
        response={response}
        onSubmit={(supplement) =>
          onClarificationSubmit(turn.id, supplement)
        }
        onSkip={() => onClarificationSkip(turn.id)}
      />
    );
  }

  if (
    response.status === "SUCCEEDED_FIRST_PASS" ||
    response.status === "SUCCEEDED_REPAIRED"
  ) {
    return <QueryResultCard response={response} />;
  }

  // Error states
  return (
    <ErrorCard
      response={response}
      onRetry={() => onRetry(turn.id)}
      onModifyQuestion={() => onModifyQuestion(turn.question)}
    />
  );
}
