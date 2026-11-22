// SPDX-License-Identifier: AGPL-3.0-or-later
import { useRef, useState } from 'react';
import { ScrollView, View, type ScrollViewInstance } from 'react-native';

import { ApiError } from '@/api/errors';
import { useResolveAction } from '@/api/hooks';
import { AppText } from '@/components/AppText';
import { Banner } from '@/components/Banner';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { confirmAction } from '@/components/confirm';
import { SwitchRow } from '@/components/SwitchRow';
import { TextField } from '@/components/TextField';
import { useConnection } from '@/connection/ConnectionProvider';
import { markNoticeSeen, noticeSeen } from '@/features/forms/seenNotice';
import { ActionCard } from '@/features/chat/ActionCard';
import { useChat, type Message } from '@/features/chat/useChat';
import { t, type MessageKey } from '@/i18n';
import { useTheme } from '@/theme';

const NOTICE_KEY = 'annona.chat_notice_seen';

function toolLabel(name: string): string {
  const key = `chat.tool.${name}` as MessageKey;
  const text = t(key);
  return text === key ? t('chat.tool.other') : text;
}

function Bubble({ message, onResolve }: { message: Message; onResolve: (actionId: number, confirm: boolean) => void }) {
  const { colors, radius, spacing } = useTheme();
  const mine = message.role === 'user';
  const running = message.tools.filter((x) => x.status === 'running');
  return (
    <View style={{ gap: spacing.sm, alignItems: mine ? 'flex-end' : 'flex-start' }}>
      {message.text ? (
        <View
          accessibilityRole="text"
          style={{
            maxWidth: '92%',
            padding: spacing.md,
            borderRadius: radius.lg,
            backgroundColor: mine ? colors.primary : colors.surface,
            borderWidth: mine ? 0 : 1,
            borderColor: colors.border,
          }}
        >
          <AppText color={mine ? colors.onPrimary : colors.text}>{message.text}</AppText>
        </View>
      ) : null}
      {!mine && running.length ? (
        <AppText variant="caption" muted accessibilityLiveRegion="polite">
          {toolLabel(running[running.length - 1].name)}
        </AppText>
      ) : null}
      {!mine ? message.tools.filter((x) => x.status === 'failed').map((x) => (
        <AppText key={x.id} variant="caption" muted>
          {toolLabel(x.name)} {t('chat.tool.failed')}
        </AppText>
      )) : null}
      {message.actions.map((action) => (
        <View key={action.id} style={{ alignSelf: 'stretch' }}>
          <ActionCard action={action} onResolve={(confirm) => onResolve(action.id, confirm)} />
        </View>
      ))}
      {message.limit ? <Banner>{t('chat.limit')}</Banner> : null}
      {message.failed ? <Banner kind="warning">{t('chat.error', { error: message.failed })}</Banner> : null}
    </View>
  );
}

export default function ChatScreen() {
  const { connection } = useConnection();
  const { colors, spacing } = useTheme();
  const chat = useChat(connection);
  const resolve = useResolveAction();
  const [text, setText] = useState('');
  const [careful, setCareful] = useState(false);
  const scroller = useRef<ScrollViewInstance>(null);

  async function submit() {
    const message = text.trim();
    if (!message || chat.busy) return;
    if (!(await noticeSeen(NOTICE_KEY))) {
      const ok = await confirmAction(t('chat.privacy.title'), t('chat.privacy.message'), t('chat.privacy.ok'), t('common.cancel'));
      if (!ok) return;
      await markNoticeSeen(NOTICE_KEY);
    }
    setText('');
    void chat.send(message, careful ? 'large' : 'small');
  }

  function resolveAction(messageId: number, actionId: number, confirm: boolean) {
    chat.setAction(messageId, actionId, { status: 'busy' });
    resolve.mutate(
      { id: actionId, confirm },
      {
        onSuccess: (out) => {
          const failed = out.status === 'failed';
          chat.setAction(messageId, actionId, {
            status: failed ? 'failed' : confirm ? 'confirmed' : 'cancelled',
            error: failed ? String((out.result as { error?: string } | null)?.error ?? '') : undefined,
          });
        },
        onError: (error) =>
          chat.setAction(messageId, actionId, {
            status: error instanceof ApiError && error.code === 'action_closed' ? 'cancelled' : 'failed',
            error: error instanceof Error ? error.message : '',
          }),
      },
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <ScrollView
        ref={scroller}
        contentContainerStyle={{ padding: spacing.lg, gap: spacing.lg }}
        onContentSizeChange={() => scroller.current?.scrollToEnd({ animated: true })}
        keyboardShouldPersistTaps="handled"
      >
        {chat.messages.length === 0 ? (
          <Card style={{ gap: 8 }}>
            <AppText>{t('chat.intro')}</AppText>
            <AppText variant="caption" muted>
              {t('chat.examples')}
            </AppText>
          </Card>
        ) : null}
        {chat.messages.map((m) => (
          <Bubble key={m.id} message={m} onResolve={(actionId, confirm) => resolveAction(m.id, actionId, confirm)} />
        ))}
        {chat.busy && chat.messages[chat.messages.length - 1]?.text === '' && chat.messages[chat.messages.length - 1]?.tools.length === 0 ? (
          <AppText muted accessibilityLiveRegion="polite">
            {t('chat.thinking')}
          </AppText>
        ) : null}
      </ScrollView>
      <View style={{ padding: spacing.md, gap: spacing.sm, backgroundColor: colors.surface, borderTopWidth: 1, borderColor: colors.border }}>
        <SwitchRow label={t('chat.careful')} value={careful} onChange={setCareful} />
        <TextField label={t('chat.input')} value={text} onChangeText={setText} autoCapitalize="sentences" multiline onSubmitEditing={() => void submit()} />
        <View style={{ flexDirection: 'row', gap: spacing.sm }}>
          {chat.busy ? (
            <Button variant="secondary" label={t('chat.stop')} onPress={chat.stop} />
          ) : (
            <Button label={t('chat.send')} onPress={() => void submit()} disabled={!text.trim()} />
          )}
          {chat.messages.length ? <Button variant="ghost" label={t('chat.new')} onPress={chat.reset} /> : null}
        </View>
      </View>
    </View>
  );
}
