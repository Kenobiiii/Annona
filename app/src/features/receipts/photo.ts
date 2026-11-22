// SPDX-License-Identifier: AGPL-3.0-or-later
import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';
import * as ImagePicker from 'expo-image-picker';

export type PhotoSource = 'camera' | 'gallery';

/** The long side of the photo sent to the server: legible receipts, a fraction of the cost. */
export const MAX_WIDTH = 1600;
const QUALITY = 0.7;

export class PermissionDenied extends Error {
  constructor() {
    super('camera permission denied');
    this.name = 'PermissionDenied';
  }
}

/** Shrink and re-encode as JPEG; returns the new file's uri. */
export async function shrink(uri: string, width?: number): Promise<string> {
  const context = ImageManipulator.manipulate(uri);
  if (width && width > MAX_WIDTH) context.resize({ width: MAX_WIDTH });
  const image = await context.renderAsync();
  const saved = await image.saveAsync({ compress: QUALITY, format: SaveFormat.JPEG });
  return saved.uri;
}

/** Take or choose a receipt photo. Returns the ready-to-upload uri, or null if cancelled. */
export async function pickReceiptPhoto(source: PhotoSource): Promise<string | null> {
  if (source === 'camera') {
    const permission = await ImagePicker.requestCameraPermissionsAsync();
    if (!permission.granted) throw new PermissionDenied();
  }
  const launch = source === 'camera' ? ImagePicker.launchCameraAsync : ImagePicker.launchImageLibraryAsync;
  const result = await launch({ mediaTypes: ['images'], quality: 1 });
  if (result.canceled || result.assets.length === 0) return null;
  const asset = result.assets[0];
  return shrink(asset.uri, asset.width);
}
