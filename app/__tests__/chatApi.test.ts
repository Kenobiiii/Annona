// SPDX-License-Identifier: AGPL-3.0-or-later
import { fetch as streamingFetch } from 'expo/fetch';

import { parseSse, streamChat, type ChatEvent } from '@/api/chat';
import { ApiError } from '@/api/errors';

jest.mock('expo/fetch', () => ({ fetch: jest.fn() }));

const fetchMock = streamingFetch as unknown as jest.Mock;
const CONNECTION = { baseUrl: 'http://annona.test:8000', token: 'tok' };
const REQUEST = { message: 'hola', history: [], tier: 'small' as const };
const sse = (name: string, data: object) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;

function streamOf(chunks: string[]) {
  const encoder = new TextEncoder();
  let i = 0;
  return { getReader: () => ({ read: async () => (i < chunks.length ? { done: false, value: encoder.encode(chunks[i++]) } : { done: true, value: undefined }) }) };
}

async function collect(gen: AsyncGenerator<ChatEvent>) {
  const out: ChatEvent[] = [];
  for await (const event of gen) out.push(event);
  return out;
}

describe('parseSse', () => {
  it('returns complete events and keeps the unfinished rest', () => {
    const { events, rest } = parseSse(sse('text', { delta: 'Ho' }) + sse('text', { delta: 'la' }) + 'event: text\ndata: {"del');
    expect(events).toEqual([{ type: 'text', delta: 'Ho' }, { type: 'text', delta: 'la' }]);
    expect(rest).toBe('event: text\ndata: {"del');
  });

  it('skips a damaged event and keeps going', () => {
    const { events } = parseSse('event: text\ndata: {oops\n\n' + sse('done', { text: 'x', stopped: 'answered', iterations: 1, proposals: [] }));
    expect(events.map((e) => e.type)).toEqual(['done']);
  });

  it('understands accents and every event type', () => {
    const all =
      sse('text', { delta: 'qué' }) +
      sse('tool_start', { id: 'a', name: 'get_pantry' }) +
      sse('tool_end', { id: 'a', name: 'get_pantry', ok: true, summary: 'ok' }) +
      sse('action', { id: 3, tool: 'update_pantry', summary: 'Despensa: añadir 500 g' }) +
      sse('notice', { code: 'limit' }) +
      sse('error', { message: 'boom' });
    expect(parseSse(all).events.map((e) => e.type)).toEqual(['text', 'tool_start', 'tool_end', 'action', 'notice', 'error']);
    expect(parseSse(sse('text', { delta: 'qué' })).events[0]).toEqual({ type: 'text', delta: 'qué' });
  });
});

describe('streamChat', () => {
  beforeEach(() => fetchMock.mockReset());

  it('sends the token and the request, and yields events even when chunks split them', async () => {
    const payload = sse('text', { delta: 'Hola' }) + sse('done', { text: 'Hola', stopped: 'answered', iterations: 1, proposals: [] });
    fetchMock.mockResolvedValue({ ok: true, status: 200, body: streamOf([payload.slice(0, 20), payload.slice(20, 60), payload.slice(60)]) });
    const events = await collect(streamChat(CONNECTION, REQUEST));
    expect(events.map((e) => e.type)).toEqual(['text', 'done']);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://annona.test:8000/api/v1/chat');
    expect(init.headers.Authorization).toBe('Bearer tok');
    expect(JSON.parse(init.body)).toEqual(REQUEST);
  });

  it('turns a refused request into the server error', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 401, json: async () => ({ error: { code: 'unauthorized', message: 'wrong token' } }) });
    await expect(collect(streamChat(CONNECTION, REQUEST))).rejects.toMatchObject({ code: 'unauthorized', status: 401 });
  });

  it('reports a network failure as such', async () => {
    fetchMock.mockRejectedValue(new Error('Network request failed'));
    await expect(collect(streamChat(CONNECTION, REQUEST))).rejects.toBeInstanceOf(ApiError);
    await expect(collect(streamChat(CONNECTION, REQUEST))).rejects.toMatchObject({ code: 'network' });
  });
});
