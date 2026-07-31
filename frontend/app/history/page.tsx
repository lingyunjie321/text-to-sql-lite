"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Search, Trash2, Eye, ClipboardList } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { StatusBadge } from "@/components/workbench/StatusBadge";
import {
  loadConversations,
  deleteConversation,
  clearAllConversations,
  searchConversations,
  formatRelativeTime,
  type Conversation,
} from "@/lib/history";

export default function HistoryPage() {
  const router = useRouter();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [deleteId, setDeleteId] = useState<string | null>(null);

  useEffect(() => {
    setConversations(loadConversations());
  }, []);

  const filtered = searchQuery
    ? searchConversations(searchQuery)
    : conversations;

  const handleView = (conv: Conversation) => {
    // For now, we just go to home. Full conversation restore would require
    // passing the conversation data via a global state or URL.
    router.push(`/?conversation=${conv.id}`);
  };

  const handleDelete = (id: string) => {
    deleteConversation(id);
    setConversations(loadConversations());
    setDeleteId(null);
  };

  const handleClearAll = () => {
    clearAllConversations();
    setConversations([]);
    setShowClearConfirm(false);
  };

  return (
    <div className="mx-auto w-full max-w-[800px] px-4 py-6 md:px-6">
      <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">
        历史记录
      </h1>

      {/* Search */}
      <div className="relative mt-4">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-tertiary)]" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="搜索问题、SQL 或状态..."
          className="w-full rounded-md border border-[var(--color-border-strong)] bg-white py-2.5 pl-10 pr-4 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:border-[var(--color-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20"
        />
      </div>

      {/* Conversation list */}
      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <ClipboardList className="h-12 w-12 text-[var(--color-text-tertiary)]" />
          <p className="mt-4 text-base font-medium text-[var(--color-text-secondary)]">
            {searchQuery
              ? `没有找到匹配「${searchQuery}」的记录`
              : "还没有查询历史记录"}
          </p>
          {!searchQuery && (
            <>
              <p className="mt-1 text-sm text-[var(--color-text-tertiary)]">
                去工作台提一个问题，记录会出现在这里
              </p>
              <Button
                variant="secondary"
                size="md"
                className="mt-6"
                onClick={() => router.push("/")}
              >
                去提问 →
              </Button>
            </>
          )}
        </div>
      ) : (
        <>
          <div className="mt-4 space-y-3">
            {filtered.map((conv) => {
              const lastRecord = conv.records[conv.records.length - 1];
              if (!lastRecord) return null;

              return (
                <div
                  key={conv.id}
                  className="rounded-lg border border-[var(--color-border)] bg-white p-4 shadow-sm transition-shadow duration-150 hover:shadow-md"
                >
                  {/* Header */}
                  <div className="flex items-center justify-between">
                    <StatusBadge
                      status={lastRecord.response.status}
                      subtitle={formatRelativeTime(
                        lastRecord.timestamp,
                      )}
                    />
                  </div>

                  {/* Question */}
                  <p className="mt-2 text-sm text-[var(--color-text-primary)]">
                    {lastRecord.question}
                  </p>

                  {/* SQL preview (if available) */}
                  {lastRecord.response.sql && (
                    <p className="mt-1 truncate font-mono text-xs text-[var(--color-text-tertiary)]">
                      {lastRecord.response.sql}
                    </p>
                  )}

                  {/* Actions */}
                  <div className="mt-3 flex justify-end gap-2">
                    <button
                      onClick={() => handleView(conv)}
                      className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium text-[var(--color-text-secondary)] transition-colors duration-150 hover:bg-[var(--color-bg-subtle)]"
                    >
                      <Eye className="h-3.5 w-3.5" />
                      查看
                    </button>
                    <button
                      onClick={() => setDeleteId(conv.id)}
                      className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium text-[var(--color-text-secondary)] transition-colors duration-150 hover:bg-[var(--color-error-light)] hover:text-[var(--color-error)]"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      删除
                    </button>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Clear all */}
          <div className="mt-6 flex justify-center">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowClearConfirm(true)}
            >
              清空全部历史
            </Button>
          </div>
        </>
      )}

      {/* Delete confirmation */}
      {deleteId && (
        <ConfirmDialog
          message="确定删除这条记录？"
          onConfirm={() => handleDelete(deleteId)}
          onCancel={() => setDeleteId(null)}
        />
      )}

      {/* Clear all confirmation */}
      {showClearConfirm && (
        <ConfirmDialog
          message="确定清空全部历史记录？此操作不可撤销。"
          onConfirm={handleClearAll}
          onCancel={() => setShowClearConfirm(false)}
        />
      )}
    </div>
  );
}

function ConfirmDialog({
  message,
  onConfirm,
  onCancel,
}: {
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div className="animate-fade-in rounded-xl border border-[var(--color-border)] bg-white p-6 shadow-lg">
        <p className="text-sm text-[var(--color-text-primary)]">{message}</p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="md" onClick={onCancel}>
            取消
          </Button>
          <Button variant="danger" size="md" onClick={onConfirm}>
            确定
          </Button>
        </div>
      </div>
    </div>
  );
}
