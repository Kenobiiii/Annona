// SPDX-License-Identifier: AGPL-3.0-or-later
import { File } from 'expo-file-system';
import { Platform } from 'react-native';

/**
 * The multipart body of a receipt upload.
 *
 * Expo replaces the global `fetch` with `expo/fetch`, which rejects React Native's
 * `{ uri, name, type }` form parts ("Unsupported FormDataPart implementation"). On native we
 * attach an expo-file-system `File` (a real Blob that can read its own bytes); the web needs
 * the bytes as a Blob.
 */
export async function buildReceiptForm(uri: string): Promise<FormData> {
  const form = new FormData();
  if (Platform.OS === 'web') {
    const blob = await (await fetch(uri)).blob();
    form.append('file', blob, 'ticket.jpg');
  } else {
    form.append('file', new File(uri));
  }
  return form;
}
