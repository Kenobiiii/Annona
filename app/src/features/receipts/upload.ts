// SPDX-License-Identifier: AGPL-3.0-or-later
import { Platform } from 'react-native';

/** The multipart body of a receipt upload. React Native sends a file by its uri; the web needs the bytes. */
export async function buildReceiptForm(uri: string): Promise<FormData> {
  const form = new FormData();
  if (Platform.OS === 'web') {
    const blob = await (await fetch(uri)).blob();
    form.append('file', blob, 'ticket.jpg');
  } else {
    form.append('file', { uri, name: 'ticket.jpg', type: 'image/jpeg' } as unknown as Blob);
  }
  return form;
}
