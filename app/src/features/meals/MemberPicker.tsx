// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Schemas } from '@/api/client';
import { Segmented } from '@/components/Segmented';
import { t } from '@/i18n';

/** Choose whose portions to show; hidden when the household has one person. */
export function MemberPicker({
  members,
  value,
  onChange,
}: {
  members: Schemas['ProfileOut'][];
  value?: number;
  onChange: (id: number) => void;
}) {
  if (members.length < 2) return null;
  return (
    <Segmented
      label={t('today.for')}
      options={members.map((m) => ({ value: String(m.profile.id), label: m.profile.name }))}
      value={String(value ?? members[0].profile.id)}
      onChange={(id) => onChange(Number(id))}
    />
  );
}
