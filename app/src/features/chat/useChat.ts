// SPDX-License-Identifier: AGPL-3.0-or-later
import { useCallback, useRef, useState } from 'react';

import { streamChat, type ChatEvent } from '@/api/chat';
import type { Connection } from '@/connection/storage';

export type ActionState = {
  id: number;
  summary: string;
  status: 'pending' | 'busy' | 'confirmed' | 'cancelled' | 'failed';
  error?: string;
};

export type ToolState = { id: string; name: string; status: 'running' | 'done' | 'failed' };

export type Message = {
  id: number;
  role: 'user' | 'assistant';
  text: string;
  tools: ToolState[];
  actions: ActionState[];
  limit?: boolean; // a limit stopped the turn
  failed?: string;
};

/** A finished (or broken) turn leaves no lookup "in progress". */
function closeTools(tools: ToolState[]): ToolState[] {
  return tools.map((x) => (x.status === 'running' ? { ...x, status: 'done' } : x));
}

/** How many past messages are sent along (the server keeps its own, smaller window). */
export const HISTORY_SENT = 20;

export function useChat(connection: Connection | null) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  const next = useRef(1);
  const abort = useRef<AbortController | null>(null);

  const update = useCallback((id: number, change: (m: Message) => Message) => {
    setMessages((cur) => cur.map((m) => (m.id === id ? change(m) : m)));
  }, []);

  const apply = useCallback(
    (id: number, event: ChatEvent) => {
      update(id, (m) => {
        switch (event.type) {
          case 'text':
            return { ...m, text: m.text + event.delta };
          case 'tool_start':
            return { ...m, tools: [...m.tools, { id: event.id, name: event.name, status: 'running' }] };
          case 'tool_end':
            return {
              ...m,
              tools: m.tools.map((x) => (x.id === event.id ? { ...x, status: event.ok ? 'done' : 'failed' } : x)),
            };
          case 'action':
            return { ...m, actions: [...m.actions, { id: event.id, summary: event.summary, status: 'pending' }] };
          case 'notice':
            return { ...m, limit: true };
          case 'done':
            return { ...m, text: m.text || event.text, tools: closeTools(m.tools) };
          case 'error':
            return { ...m, failed: event.message, tools: closeTools(m.tools) };
        }
      });
    },
    [update],
  );

  const send = useCallback(
    async (text: string, tier: 'small' | 'large') => {
      if (!connection || busy || !text.trim()) return;
      const history = messages
        .filter((m) => m.text.trim())
        .slice(-HISTORY_SENT)
        .map((m) => ({ role: m.role, text: m.text }));
      const userId = next.current++;
      const replyId = next.current++;
      setMessages((cur) => [
        ...cur,
        { id: userId, role: 'user', text, tools: [], actions: [] },
        { id: replyId, role: 'assistant', text: '', tools: [], actions: [] },
      ]);
      setBusy(true);
      abort.current = new AbortController();
      try {
        for await (const event of streamChat(connection, { message: text, history, tier }, abort.current.signal)) {
          apply(replyId, event);
        }
      } catch (error) {
        if (!(error instanceof Error && error.name === 'AbortError')) {
          update(replyId, (m) => ({
            ...m,
            failed: error instanceof Error ? error.message : String(error),
            tools: closeTools(m.tools),
          }));
        }
      } finally {
        setBusy(false);
        abort.current = null;
      }
    },
    [apply, busy, connection, messages, update],
  );

  const setAction = useCallback((messageId: number, actionId: number, change: Partial<ActionState>) => {
    update(messageId, (m) => ({ ...m, actions: m.actions.map((a) => (a.id === actionId ? { ...a, ...change } : a)) }));
  }, [update]);

  const stop = useCallback(() => abort.current?.abort(), []);
  const reset = useCallback(() => {
    abort.current?.abort();
    setMessages([]);
  }, []);

  return { messages, busy, send, stop, reset, setAction };
}
