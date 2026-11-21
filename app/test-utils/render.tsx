// SPDX-License-Identifier: AGPL-3.0-or-later
import { QueryClient } from '@tanstack/react-query';
import { act, render } from '@testing-library/react-native';
import * as SecureStore from 'expo-secure-store';
import type { ReactElement, ReactNode } from 'react';

import { QueryProvider } from '@/api/providers';
import { ConnectionProvider, useConnection } from '@/connection/ConnectionProvider';

export const CONNECTION = { baseUrl: 'http://annona.test:8000', token: 'test-token' };

export function seedConnection(connection: typeof CONNECTION | null = CONNECTION) {
  const data = (SecureStore as unknown as { __data: Map<string, string> }).__data;
  data.clear();
  if (connection) {
    data.set('annona.server_url', connection.baseUrl);
    data.set('annona.token', connection.token);
  }
}

function WhenReady({ children }: { children: ReactNode }) {
  const { status } = useConnection();
  return status === 'loading' ? null : <>{children}</>;
}

/** Render with a connected app and a fake server (no retries, no cache between tests). */
export async function renderConnected(ui: ReactElement, fetchImpl: (r: Request) => Promise<Response>) {
  seedConnection();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const result = await render(
    <ConnectionProvider>
      <QueryProvider client={client} fetchImpl={fetchImpl}>
        <WhenReady>{ui}</WhenReady>
      </QueryProvider>
    </ConnectionProvider>,
  );
  await settle();
  return result;
}

/** Let the stored connection load (it is read asynchronously from the secure store). */
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

/** Render without a saved connection (first run). */
export async function renderFirstRun(ui: ReactElement, fetchImpl?: (r: Request) => Promise<Response>) {
  seedConnection(null);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const result = await render(
    <ConnectionProvider>
      <QueryProvider client={client} fetchImpl={fetchImpl}>
        <WhenReady>{ui}</WhenReady>
      </QueryProvider>
    </ConnectionProvider>,
  );
  await settle();
  return result;
}
