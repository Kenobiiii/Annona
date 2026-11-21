// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react';
import { View } from 'react-native';

import { testConnection } from '@/api/client';
import { ApiError } from '@/api/errors';
import { AppText } from '@/components/AppText';
import { Banner } from '@/components/Banner';
import { Button } from '@/components/Button';
import { describeError } from '@/components/StateViews';
import { TextField } from '@/components/TextField';
import { useConnection } from '@/connection/ConnectionProvider';
import { isCleartext, normalizeServerUrl } from '@/connection/url';
import { t } from '@/i18n';
import { useTheme } from '@/theme';

type Props = {
  onSaved?: () => void;
  /** Injected in tests. */
  fetchImpl?: (request: Request) => Promise<Response>;
};

export function ConnectionForm({ onSaved, fetchImpl }: Props) {
  const { connection, save } = useConnection();
  const { colors, spacing } = useTheme();
  const [url, setUrl] = useState(connection?.baseUrl ?? '');
  const [token, setToken] = useState(connection?.token ?? '');
  const [errors, setErrors] = useState<{ url?: string; token?: string }>({});
  const [status, setStatus] = useState<{ kind: 'idle' | 'testing' | 'ok' | 'failed'; text?: string }>({
    kind: 'idle',
  });

  /** Validate the fields; returns the connection to use, or null (and shows what is wrong). */
  function validate() {
    const next: { url?: string; token?: string } = {};
    const parsed = normalizeServerUrl(url);
    if (!parsed.ok) {
      next.url = t(
        parsed.error === 'empty'
          ? 'connect.invalid.empty'
          : parsed.error === 'protocol'
            ? 'connect.invalid.protocol'
            : 'connect.invalid.url',
      );
    }
    if (!token.trim()) next.token = t('connect.invalid.token');
    setErrors(next);
    return parsed.ok && !next.token ? { baseUrl: parsed.url, token: token.trim() } : null;
  }

  async function test() {
    const candidate = validate();
    if (!candidate) return;
    setStatus({ kind: 'testing' });
    try {
      const version = await testConnection(candidate, fetchImpl);
      setStatus({ kind: 'ok', text: t('connect.ok', { version }) });
    } catch (error) {
      const info = describeError(error);
      const detail = error instanceof ApiError && info.hint ? `${info.message} ${info.hint}` : info.message;
      setStatus({ kind: 'failed', text: detail });
    }
  }

  async function saveAndContinue() {
    const candidate = validate();
    if (!candidate) return;
    await save(candidate);
    onSaved?.();
  }

  const typed = normalizeServerUrl(url);
  const cleartext = typed.ok && isCleartext(typed.url);

  return (
    <View style={{ gap: spacing.lg }}>
      <TextField
        label={t('connect.url')}
        value={url}
        onChangeText={setUrl}
        placeholder={t('connect.url.placeholder')}
        keyboardType="url"
        error={errors.url}
      />
      <TextField label={t('connect.token')} value={token} onChangeText={setToken} secret error={errors.token} />
      {cleartext ? <Banner kind="warning">{t('connect.cleartext')}</Banner> : null}
      {status.kind === 'ok' || status.kind === 'failed' ? (
        <AppText
          accessibilityLiveRegion="polite"
          color={status.kind === 'ok' ? colors.primary : colors.danger}
        >
          {status.text}
        </AppText>
      ) : null}
      <Button
        label={status.kind === 'testing' ? t('connect.testing') : t('connect.test')}
        onPress={() => void test()}
        variant="secondary"
        loading={status.kind === 'testing'}
      />
      <Button label={t('connect.save')} onPress={() => void saveAndContinue()} />
    </View>
  );
}
