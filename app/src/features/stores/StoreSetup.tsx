// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react';
import { View } from 'react-native';

import { ApiError } from '@/api/errors';
import { useDeleteStoreConnection, usePutStoreConnection, useStoreConnection } from '@/api/hooks';
import { AppText } from '@/components/AppText';
import { Banner } from '@/components/Banner';
import { Button } from '@/components/Button';
import { confirmAction } from '@/components/confirm';
import { LoadingState } from '@/components/StateViews';
import { TextField } from '@/components/TextField';
import { t, type MessageKey } from '@/i18n';

/** The store's display name (falls back to the server's). */
export function storeName(storeId: string, fallback?: string): string {
  const key = `store.name.${storeId}` as MessageKey;
  const name = t(key);
  return name === key ? (fallback ?? storeId) : name;
}

/** The notice in the app's language when there is a translation; the server's text otherwise. */
function noticeText(storeId: string, serverText: string | null): string | null {
  const key = `store.notice.${storeId}` as MessageKey;
  const text = t(key);
  return text === key ? serverText : text;
}

export function storeErrorMessage(error: unknown, store: string): string {
  if (error instanceof ApiError && error.code === 'store_error') return t('store.error.unavailable', { store });
  if (error instanceof ApiError && error.code === 'network') return t('error.network');
  return error instanceof ApiError && error.message ? error.message : t('error.generic');
}

type Props = {
  storeId: string;
  suggestedPostalCode?: string | null; // e.g. read from the receipt
  manage?: boolean; // settings: show the state and let the person change or withdraw it
};

/** Accept an opt-in store's notice and say where you shop. Nothing reaches the store before. */
export function StoreSetup({ storeId, suggestedPostalCode, manage = false }: Props) {
  const connection = useStoreConnection(storeId);
  const save = usePutStoreConnection(storeId);
  const remove = useDeleteStoreConnection(storeId);
  const [editing, setEditing] = useState(false);
  const [postal, setPostal] = useState<string | null>(null);

  if (connection.isPending) return <LoadingState />;
  if (connection.isError) return <AppText variant="caption">{storeErrorMessage(connection.error, storeName(storeId))}</AppText>;
  const c = connection.data;
  const name = storeName(storeId, c.name);
  const needsNotice = c.opt_in && !c.notice_accepted_at;
  const value = postal ?? c.postal_code ?? suggestedPostalCode ?? '';
  const fromReceipt = !c.postal_code && !!suggestedPostalCode && value === suggestedPostalCode;

  if (c.ready && !editing) {
    if (!manage) return null;
    return (
      <View style={{ gap: 8 }}>
        <AppText>{t('store.ready', { store: name, postal: c.postal_code ?? '—' })}</AppText>
        <Button variant="secondary" label={t('store.postal.change')} onPress={() => setEditing(true)} />
        <Button
          variant="ghost"
          label={t('store.disconnect', { store: name })}
          loading={remove.isPending}
          onPress={async () => {
            if (await confirmAction(t('store.disconnect.title', { store: name }), t('store.disconnect.message'), t('store.disconnect.confirm'), t('common.cancel'))) {
              remove.mutate();
            }
          }}
        />
      </View>
    );
  }

  const valid = !c.supports_postcode || /^[0-9A-Za-z -]{3,10}$/.test(value.trim());
  const submit = async () => {
    await save.mutateAsync({ postal_code: c.supports_postcode ? value.trim() : null, accept_notice: needsNotice });
    setEditing(false);
  };
  const notice = noticeText(storeId, c.notice);
  return (
    <View style={{ gap: 8 }}>
      {needsNotice ? (
        <>
          <AppText variant="label">{t('store.notice.title', { store: name })}</AppText>
          <Banner kind="warning">{notice ?? ''}</Banner>
          <AppText variant="caption" muted>
            {t('store.privacy', { store: name })}
          </AppText>
        </>
      ) : null}
      {c.supports_postcode ? (
        <>
          <TextField label={t('store.postal')} value={value} onChangeText={setPostal} keyboardType="number-pad" />
          <AppText variant="caption" muted>
            {fromReceipt ? t('store.postal.fromReceipt') : t('store.postal.hint', { store: name })}
          </AppText>
        </>
      ) : null}
      {save.isError ? <AppText variant="caption">{storeErrorMessage(save.error, name)}</AppText> : null}
      <Button
        label={needsNotice ? t('store.accept', { store: name }) : t('common.save')}
        disabled={!valid}
        loading={save.isPending}
        onPress={() => void submit().catch(() => undefined)}
      />
      {editing ? <Button variant="ghost" label={t('common.cancel')} onPress={() => setEditing(false)} /> : null}
    </View>
  );
}
