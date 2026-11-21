// SPDX-License-Identifier: AGPL-3.0-or-later
import createClient from 'openapi-fetch';

import { ApiError, errorFromBody } from './errors';
import type { components, paths } from './schema';
import type { Connection } from '@/connection/storage';

export type Schemas = components['schemas'];
export type ApiClient = ReturnType<typeof createApi>;

type Fetch = (request: Request) => Promise<Response>;

/** A typed client for the Annona REST API (types generated from the server's OpenAPI schema). */
export function createApi(connection: Connection, fetchImpl?: Fetch) {
  return createClient<paths>({
    baseUrl: connection.baseUrl,
    headers: { Authorization: `Bearer ${connection.token}` },
    fetch: fetchImpl ?? ((request) => fetch(request)),
  });
}

type Result<T> = { data?: T; error?: unknown; response: Response };

/** Turn an openapi-fetch result into its data, or throw an :class:`ApiError`. */
export async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  let result: Result<T>;
  try {
    result = await call;
  } catch (cause) {
    throw new ApiError(0, 'network', cause instanceof Error ? cause.message : 'network error');
  }
  if (result.error !== undefined || !result.response.ok) {
    throw errorFromBody(result.response.status, result.error);
  }
  return result.data as T;
}

/** Check a server address and token before saving them (does not touch stored data). */
export async function testConnection(connection: Connection, fetchImpl?: Fetch): Promise<string> {
  const api = createApi(connection, fetchImpl);
  const health = await unwrap(api.GET('/health'));
  await unwrap(api.GET('/api/v1/stores')); // needs the token: proves it is accepted
  return (health as { version?: string }).version ?? '?';
}
