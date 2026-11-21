// SPDX-License-Identifier: AGPL-3.0-or-later
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { QueryProvider } from '@/api/providers';
import { ConnectionProvider } from '@/connection/ConnectionProvider';

export default function RootLayout() {
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <ConnectionProvider>
          <QueryProvider>
            <StatusBar style="auto" />
            <Stack screenOptions={{ headerShown: false }} />
          </QueryProvider>
        </ConnectionProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
