import { useCallback, useEffect, useSyncExternalStore } from 'react';
import { Conversation, Message } from '@/constants/types';
import { getItem, setItem, STORAGE_KEYS } from '@/services/storage';

let conversations: Conversation[] = [];
let isLoaded = false;
let listeners = new Set<() => void>();

function emit() {
  listeners.forEach((l) => l());
}

function getSnapshot() {
  return conversations;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

async function persist() {
  await setItem(STORAGE_KEYS.conversations, conversations);
}

async function loadFromStorage() {
  if (isLoaded) return;
  const stored = await getItem<Conversation[]>(STORAGE_KEYS.conversations);
  if (stored) {
    // Migrate expertId → agentId for existing conversations
    conversations = stored.map((c) => ({
      ...c,
      agentId: c.agentId || c.expertId,
    }));
  }
  isLoaded = true;
  emit();
}

if (typeof window !== 'undefined') {
  loadFromStorage();
}

export function useConversations() {
  const convos = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  useEffect(() => {
    loadFromStorage();
  }, []);

  const createConversation = useCallback((agentId: string): Conversation => {
    const conv: Conversation = {
      id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
      expertId: agentId,
      agentId,
      title: 'New Chat',
      messages: [],
      lastMessageAt: Date.now(),
      createdAt: Date.now(),
    };
    conversations = [conv, ...conversations];
    emit();
    persist();
    return conv;
  }, []);

  const addMessage = useCallback((conversationId: string, msg: Message) => {
    conversations = conversations.map((c) => {
      if (c.id !== conversationId) return c;
      const title =
        c.messages.length === 0 && msg.role === 'user'
          ? msg.content.slice(0, 40)
          : c.title;
      return {
        ...c,
        title,
        messages: [...c.messages, msg],
        lastMessageAt: msg.timestamp,
      };
    });
    conversations = [...conversations].sort((a, b) => b.lastMessageAt - a.lastMessageAt);
    emit();
    persist();
  }, []);

  const getConversation = useCallback(
    (id: string) => conversations.find((c) => c.id === id),
    [convos]
  );

  /** Update (or append) a message by ID — used for streaming deltas. */
  const updateMessage = useCallback(
    (conversationId: string, messageId: string, content: string) => {
      conversations = conversations.map((c) => {
        if (c.id !== conversationId) return c;
        const existing = c.messages.find((m) => m.id === messageId);
        if (existing) {
          return {
            ...c,
            messages: c.messages.map((m) =>
              m.id === messageId ? { ...m, content } : m,
            ),
            lastMessageAt: Date.now(),
          };
        }
        return c;
      });
      emit();
      // Debounce persistence for streaming — caller persists on completion
    },
    [],
  );

  /** Persist current state (call after streaming completes). */
  const flush = useCallback(() => {
    persist();
  }, []);

  return {
    conversations: convos,
    createConversation,
    addMessage,
    updateMessage,
    flush,
    getConversation,
  };
}
