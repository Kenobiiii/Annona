// SPDX-License-Identifier: AGPL-3.0-or-later
import { Redirect } from 'expo-router';
import { Drawer } from 'expo-router/drawer';
import { View } from 'react-native';

import { BackButton } from '@/components/BackButton';
import { LoadingState } from '@/components/StateViews';
import { useConnection } from '@/connection/ConnectionProvider';
import { t } from '@/i18n';
import { useTheme } from '@/theme';

export default function AppLayout() {
  const { status } = useConnection();
  const { colors } = useTheme();

  if (status === 'loading') {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background, justifyContent: 'center' }}>
        <LoadingState />
      </View>
    );
  }
  if (status === 'unconfigured') return <Redirect href="/connect" />;

  const detail = (title: string, fallback: '/products' | '/menu' | '/settings') => ({
    title,
    drawerItemStyle: { display: 'none' as const },
    headerLeft: () => <BackButton fallback={fallback} />,
  });

  return (
    <Drawer
      screenOptions={{
        headerStyle: { backgroundColor: colors.surface },
        headerTintColor: colors.text,
        headerTitleStyle: { fontWeight: '600' },
        drawerStyle: { backgroundColor: colors.background },
        drawerActiveTintColor: colors.primary,
        drawerInactiveTintColor: colors.text,
      }}
    >
      <Drawer.Screen name="index" options={{ title: t('nav.today'), drawerLabel: t('nav.today') }} />
      <Drawer.Screen name="products/index" options={{ title: t('nav.products'), drawerLabel: t('nav.products') }} />
      <Drawer.Screen name="menu/index" options={{ title: t('nav.menu'), drawerLabel: t('nav.menu') }} />
      <Drawer.Screen name="tools" options={{ title: t('nav.tools'), drawerLabel: t('nav.tools') }} />
      <Drawer.Screen name="shopping" options={{ title: t('nav.shopping'), drawerLabel: t('nav.shopping') }} />
      <Drawer.Screen name="settings/index" options={{ title: t('nav.settings'), drawerLabel: t('nav.settings') }} />
      <Drawer.Screen name="products/[id]" options={detail(t('nav.products'), '/products')} />
      <Drawer.Screen name="menu/create" options={detail(t('nav.menu'), '/menu')} />
      <Drawer.Screen name="settings/profile/[id]" options={detail(t('nav.settings'), '/settings')} />
    </Drawer>
  );
}
