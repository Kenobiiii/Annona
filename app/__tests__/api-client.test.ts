// SPDX-License-Identifier: AGPL-3.0-or-later
import * as SecureStore from 'expo-secure-store';

import { createApi, testConnection, unwrap } from '@/api/client';
import { ApiError, fieldErrors } from '@/api/errors';
import { clearConnection, loadConnection, saveConnection } from '@/connection/storage';
import { apiError, fakeApi, json } from '../test-utils/fakeApi';

const connection = { baseUrl: 'http://annona.test:8000', token: 'secret' };

describe('typed client', () => {
  it('sends the bearer token and returns typed data', async () => {
    let auth: string | null = null;
    const api = createApi(connection, async (request) => {
      auth = request.headers.get('authorization');
      return json({ items: [], page: 1, size: 50, total: 0 });
    });
    const data = await unwrap(api.GET('/api/v1/pantry', { params: { query: { page: 1 } } }));
    expect(auth).toBe('Bearer secret');
    expect(data.total).toBe(0);
  });

  it('turns the server error format into ApiError', async () => {
    const server = fakeApi({
      'GET /api/v1/household': () => apiError(409, 'setup_required', 'create the household first'),
    });
    const api = createApi(connection, server.fetchImpl);
    const error = await unwrap(api.GET('/api/v1/household')).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, code: 'setup_required' });
  });

  it('reports network failures as code "network"', async () => {
    const api = createApi(connection, async () => {
      throw new TypeError('Network request failed');
    });
    await expect(unwrap(api.GET('/api/v1/household'))).rejects.toMatchObject({ code: 'network', status: 0 });
  });

  it('exposes field problems of validation errors', async () => {
    const server = fakeApi({
      'POST /api/v1/profiles': () =>
        apiError(422, 'validation_error', 'bad', [{ field: 'height_cm', message: 'must be positive' }]),
    });
    const api = createApi(connection, server.fetchImpl);
    const error = await unwrap(
      api.POST('/api/v1/profiles', { body: {} as never }),
    ).catch((e) => e);
    expect(fieldErrors(error)).toEqual({ height_cm: 'must be positive' });
  });

  it('accepts 204 responses without a body', async () => {
    const server = fakeApi({ 'DELETE /api/v1/pantry/3': () => undefined });
    const api = createApi(connection, server.fetchImpl);
    await expect(
      unwrap(api.DELETE('/api/v1/pantry/{item_id}', { params: { path: { item_id: 3 } } })),
    ).resolves.toBeUndefined();
  });
});

describe('testConnection', () => {
  it('returns the server version when the token works', async () => {
    const server = fakeApi({ 'GET /health': { status: 'ok', version: '0.3.1' }, 'GET /api/v1/stores': [] });
    await expect(testConnection(connection, server.fetchImpl)).resolves.toBe('0.3.1');
  });

  it('fails with "unauthorized" for a wrong token', async () => {
    const server = fakeApi({
      'GET /health': { status: 'ok', version: '0.3.1' },
      'GET /api/v1/stores': () => apiError(401, 'unauthorized', 'missing or wrong bearer token'),
    });
    await expect(testConnection(connection, server.fetchImpl)).rejects.toMatchObject({ code: 'unauthorized' });
  });
});

describe('connection storage', () => {
  beforeEach(() => (SecureStore as unknown as { __data: Map<string, string> }).__data.clear());

  it('round-trips and clears the connection', async () => {
    expect(await loadConnection()).toBeNull();
    await saveConnection(connection);
    expect(await loadConnection()).toEqual(connection);
    await clearConnection();
    expect(await loadConnection()).toBeNull();
  });

  it('only uses key names SecureStore accepts', async () => {
    await saveConnection(connection);
    const keys = [...(SecureStore as unknown as { __data: Map<string, string> }).__data.keys()];
    expect(keys.length).toBe(2);
    for (const key of keys) expect(key).toMatch(/^[A-Za-z0-9._-]+$/);
  });
});
