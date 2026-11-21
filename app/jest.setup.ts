// SPDX-License-Identifier: AGPL-3.0-or-later
/* eslint-disable @typescript-eslint/no-require-imports -- jest.mock factories must require lazily */
jest.mock('react-native-safe-area-context', () =>
  require('react-native-safe-area-context/jest/mock').default,
);

// In-memory SecureStore.
jest.mock('expo-secure-store', () => {
  const data = new Map<string, string>();
  return {
    getItemAsync: jest.fn(async (key: string) => data.get(key) ?? null),
    setItemAsync: jest.fn(async (key: string, value: string) => void data.set(key, value)),
    deleteItemAsync: jest.fn(async (key: string) => void data.delete(key)),
    __data: data,
  };
});

jest.mock('@react-native-community/netinfo', () => ({
  __esModule: true,
  default: { addEventListener: jest.fn(() => jest.fn()) },
}));

// expo-router: navigation functions are mocks the tests can inspect (test-utils/router).
jest.mock('expo-router', () => ({
  useRouter: () => require('./test-utils/router').router,
  useLocalSearchParams: jest.fn(() => ({})),
  Redirect: () => null,
  Link: ({ children }: { children: unknown }) => children,
}));
