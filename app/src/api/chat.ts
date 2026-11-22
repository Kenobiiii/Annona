// SPDX-License-Identifier: AGPL-3.0-or-later
import { fetch as streamingFetch } from 'expo/fetch';

import { ApiError, errorFromBody } from './errors';
import type { Connection } from '@/connection/storage';

export type ChatEvent =
  | { type: 'text'; delta: string }
  | { type: 'tool_start'; id: string; name: string }
  | { type: 'tool_end'; id: string; name: string; ok: boolean; summary: string }
  | { type: 'action'; id: number; tool: string; summary: string }
  | { type: 'notice'; code: string }
  | { type: 'done'; text: string; stopped: string; iterations: number; proposals: number[] }
  | { type: 'error'; message: string };

export type ChatRequest = {
  message: string;
  history: { role: 'user' | 'assistant'; text: string }[];
  tier: 'small' | 'large';
};

/** Split a buffer of server-sent events into complete events and the unfinished rest. */
export function parseSse(buffer: string): { events: ChatEvent[]; rest: string } {
  const blocks = buffer.split('\n\n');
  const rest = blocks.pop() ?? '';
  const events: ChatEvent[] = [];
  for (const block of blocks) {
    const name = /^event: (.+)$/m.exec(block)?.[1];
    const data = /^data: (.+)$/m.exec(block)?.[1];
    if (!name || !data) continue;
    try {
      events.push({ type: name, ...JSON.parse(data) } as ChatEvent);
    } catch {
      // a damaged event is skipped; the stream goes on
    }
  }
  return { events, rest };
}

/** One chat turn as a stream of events. Throws :class:`ApiError` if the request is refused. */
export async function* streamChat(
  connection: Connection,
  request: ChatRequest,
  signal?: AbortSignal,
): AsyncGenerator<ChatEvent> {
  let response;
  try {
    response = await streamingFetch(`${connection.baseUrl}/api/v1/chat`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${connection.token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
      signal,
    });
  } catch (cause) {
    throw new ApiError(0, 'network', cause instanceof Error ? cause.message : 'network error');
  }
  if (!response.ok) {
    throw errorFromBody(response.status, await response.json().catch(() => null));
  }
  const reader = response.body?.getReader();
  if (!reader) throw new ApiError(0, 'network', 'no response stream');
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parsed = parseSse(buffer);
    buffer = parsed.rest;
    for (const event of parsed.events) yield event;
  }
  const last = parseSse(buffer + '\n\n');
  for (const event of last.events) yield event;
}
