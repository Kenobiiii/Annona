// SPDX-License-Identifier: AGPL-3.0-or-later
/** A fake Annona server for component tests: routes are "METHOD /path" -> JSON or a function. */

type Call = { method: string; path: string; query: Record<string, string>; body: unknown };
type Handler = unknown | ((call: Call) => unknown);

export function fakeApi(routes: Record<string, Handler>) {
  const calls: Call[] = [];
  const fetchImpl = async (request: Request): Promise<Response> => {
    const url = new URL(request.url);
    const hasBody = request.method !== 'GET' && request.method !== 'DELETE';
    const body = hasBody ? await request.clone().json().catch(() => undefined) : undefined;
    const call: Call = {
      method: request.method,
      path: url.pathname,
      query: Object.fromEntries(url.searchParams),
      body,
    };
    calls.push(call);
    const route = routes[`${request.method} ${url.pathname}`];
    if (route === undefined) {
      return json({ error: { code: 'not_found', message: `no fake route ${request.method} ${url.pathname}` } }, 404);
    }
    const value = typeof route === 'function' ? await (route as (c: Call) => unknown)(call) : route;
    if (value instanceof Response) return value;
    if (value === undefined && request.method === 'DELETE') return new Response(null, { status: 204 });
    return json(value ?? null, 200);
  };
  return { fetchImpl, calls, called: (key: string) => calls.filter((c) => `${c.method} ${c.path}` === key) };
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

export function apiError(status: number, code: string, message: string, details?: unknown): Response {
  return json({ error: { code, message, details } }, status);
}
