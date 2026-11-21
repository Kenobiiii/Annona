// SPDX-License-Identifier: AGPL-3.0-or-later
import NetInfo from '@react-native-community/netinfo';
import {
  focusManager,
  onlineManager,
  QueryClient,
  QueryClientProvider,
  useQueryClient,
} from '@tanstack/react-query';
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { AppState, Platform } from 'react-native';

import { createApi, type ApiClient } from './client';
import { ApiError } from './errors';
import { useConnection } from '@/connection/ConnectionProvider';

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        // Client errors (wrong token, not found...) will not fix themselves: do not retry them.
        retry: (count, error) =>
          !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 1,
      },
    },
  });
}

/** Refetch when the app returns to the foreground or the network comes back. */
function useReactNativeManagers() {
  useEffect(() => {
    if (Platform.OS === 'web') return;
    const app = AppState.addEventListener('change', (state) => {
      focusManager.setFocused(state === 'active');
    });
    // The manager calls the returned unsubscribe itself when the listener is replaced.
    onlineManager.setEventListener((setOnline) =>
      NetInfo.addEventListener((s) => setOnline(!!s.isConnected)),
    );
    return () => app.remove();
  }, []);
}

const ApiContext = createContext<ApiClient | null>(null);

function ApiProvider({ children, fetchImpl }: { children: ReactNode; fetchImpl?: (r: Request) => Promise<Response> }) {
  const { connection } = useConnection();
  const queryClient = useQueryClient();
  const client = useMemo(
    () => (connection ? createApi(connection, fetchImpl) : null),
    [connection, fetchImpl],
  );
  useEffect(() => {
    queryClient.clear(); // another server (or token): nothing cached applies
  }, [connection?.baseUrl, connection?.token, queryClient]);
  return <ApiContext.Provider value={client}>{children}</ApiContext.Provider>;
}

export function QueryProvider({
  children,
  client,
  fetchImpl,
}: {
  children: ReactNode;
  client?: QueryClient;
  fetchImpl?: (r: Request) => Promise<Response>;
}) {
  const [queryClient] = useState(() => client ?? createQueryClient());
  useReactNativeManagers();
  return (
    <QueryClientProvider client={queryClient}>
      <ApiProvider fetchImpl={fetchImpl}>{children}</ApiProvider>
    </QueryClientProvider>
  );
}

export function useApi(): ApiClient {
  const client = useContext(ApiContext);
  if (!client) throw new Error('The app is not connected to a server yet');
  return client;
}
