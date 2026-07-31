import type { QueryResponse } from "./types";

export interface HistoryRecord {
  id: string;
  timestamp: number;
  question: string;
  response: QueryResponse;
  conversationIndex: number;
}

export interface Conversation {
  id: string;
  createdAt: number;
  updatedAt: number;
  title: string;
  records: HistoryRecord[];
}

const STORAGE_KEY = "text-to-sql-history";
const MAX_CONVERSATIONS = 50;
const MAX_RECORDS_PER_CONVERSATION = 100;

export function loadConversations(): Conversation[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Conversation[];
    if (!Array.isArray(parsed)) return [];
    return parsed.sort((a, b) => b.updatedAt - a.updatedAt);
  } catch {
    return [];
  }
}

function saveConversations(conversations: Conversation[]): boolean {
  if (typeof window === "undefined") return false;
  try {
    // Enforce max conversations
    if (conversations.length > MAX_CONVERSATIONS) {
      conversations = conversations
        .sort((a, b) => b.updatedAt - a.updatedAt)
        .slice(0, MAX_CONVERSATIONS);
    }
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify(conversations),
    );
    return true;
  } catch {
    // Storage full — try removing oldest 5 and retry
    try {
      const trimmed = conversations
        .sort((a, b) => b.updatedAt - a.updatedAt)
        .slice(0, MAX_CONVERSATIONS - 5);
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify(trimmed),
      );
      return true;
    } catch {
      return false;
    }
  }
}

export function getConversation(id: string): Conversation | null {
  const conversations = loadConversations();
  return conversations.find((c) => c.id === id) ?? null;
}

export function saveRecord(
  conversationId: string,
  question: string,
  response: QueryResponse,
): Conversation {
  const conversations = loadConversations();
  let conv = conversations.find((c) => c.id === conversationId);

  const now = Date.now();
  const record: HistoryRecord = {
    id: response.request_id || `r-${now}`,
    timestamp: now,
    question,
    response,
    conversationIndex: conv ? conv.records.length : 0,
  };

  if (!conv) {
    conv = {
      id: conversationId,
      createdAt: now,
      updatedAt: now,
      title: question.slice(0, 60),
      records: [record],
    };
    conversations.push(conv);
  } else {
    conv.records.push(record);
    if (conv.records.length > MAX_RECORDS_PER_CONVERSATION) {
      conv.records = conv.records.slice(-MAX_RECORDS_PER_CONVERSATION);
    }
    conv.updatedAt = now;
    if (!conv.title) {
      conv.title = question.slice(0, 60);
    }
  }

  saveConversations(conversations);
  return conv;
}

export function deleteConversation(id: string): void {
  const conversations = loadConversations();
  const filtered = conversations.filter((c) => c.id !== id);
  saveConversations(filtered);
}

export function clearAllConversations(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(STORAGE_KEY);
}

export function searchConversations(query: string): Conversation[] {
  const conversations = loadConversations();
  if (!query.trim()) return conversations;
  const q = query.toLowerCase();
  return conversations.filter((c) =>
    c.records.some(
      (r) =>
        r.question.toLowerCase().includes(q) ||
        r.response.status.toLowerCase().includes(q),
    ),
  );
}

export function formatRelativeTime(timestamp: number): string {
  const now = Date.now();
  const diff = now - timestamp;
  const seconds = Math.floor(diff / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (seconds < 60) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  if (hours < 24) return `${hours} 小时前`;
  if (days < 7) return `${days} 天前`;
  return new Date(timestamp).toLocaleDateString("zh-CN");
}
