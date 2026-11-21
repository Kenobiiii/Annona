// SPDX-License-Identifier: AGPL-3.0-or-later
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

export type Connection = { baseUrl: string; token: string };

type KeyValue = {
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
  remove(key: string): Promise<void>;
};

// Keys may only contain letters, digits, ".", "-" and "_" (SecureStore rule).
const URL_KEY = 'annona.server_url';
const TOKEN_KEY = 'annona.token';

const secure: KeyValue = {
  get: (key) => SecureStore.getItemAsync(key),
  set: (key, value) => SecureStore.setItemAsync(key, value),
  remove: (key) => SecureStore.deleteItemAsync(key),
};

/** The browser has no secure store: the web preview (development only) uses localStorage. */
const browser: KeyValue = {
  get: async (key) => globalThis.localStorage?.getItem(key) ?? null,
  set: async (key, value) => globalThis.localStorage?.setItem(key, value),
  remove: async (key) => globalThis.localStorage?.removeItem(key),
};

export const defaultStore: KeyValue = Platform.OS === 'web' ? browser : secure;

export async function loadConnection(store: KeyValue = defaultStore): Promise<Connection | null> {
  const [baseUrl, token] = await Promise.all([store.get(URL_KEY), store.get(TOKEN_KEY)]);
  return baseUrl && token ? { baseUrl, token } : null;
}

export async function saveConnection(
  connection: Connection,
  store: KeyValue = defaultStore,
): Promise<void> {
  await Promise.all([store.set(URL_KEY, connection.baseUrl), store.set(TOKEN_KEY, connection.token)]);
}

export async function clearConnection(store: KeyValue = defaultStore): Promise<void> {
  await Promise.all([store.remove(URL_KEY), store.remove(TOKEN_KEY)]);
}
