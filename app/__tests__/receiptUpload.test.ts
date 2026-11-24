// SPDX-License-Identifier: AGPL-3.0-or-later
import { convertFormDataAsync } from 'expo/src/winter/fetch/convertFormData';

import { buildReceiptForm } from '@/features/receipts/upload';

// A stand-in for expo-file-system's File: on a phone it reads the photo's bytes natively.
jest.mock('expo-file-system', () => ({
  File: class {
    name = 'photo.jpg';
    type = 'image/jpeg';
    async bytes() {
      return new Uint8Array([0xff, 0xd8, 0xff]);
    }
  },
}));

// On a phone, FormData is React Native's (patched by Expo) and expo/fetch encodes it as below.
// Jest's Node FormData would stringify any non-Blob, hiding the bug, so use React Native's here.
const nodeFormData = globalThis.FormData;
beforeAll(() => {
  const ReactNativeFormData = jest.requireActual('react-native/Libraries/Network/FormData').default;
  // jest-expo stubs this patch out; the real one is what runs on the phone.
  jest.requireActual('expo/src/winter/FormData').installFormDataPatch(ReactNativeFormData);
  globalThis.FormData = ReactNativeFormData;
});
afterAll(() => {
  globalThis.FormData = nodeFormData;
});

describe('buildReceiptForm', () => {
  it('builds a form that expo/fetch can send (regression: "Unsupported FormDataPart implementation")', async () => {
    const form = await buildReceiptForm('file:///photo.jpg');

    const { body, boundary } = await convertFormDataAsync(form, 'B');
    const text = new TextDecoder('latin1').decode(body);

    expect(boundary).toBe('B');
    expect(text).toContain('content-disposition: form-data; name="file"; filename="photo.jpg"');
    expect(text).toContain('content-type: image/jpeg');
    expect(Array.from(body)).toEqual(expect.arrayContaining([0xff, 0xd8, 0xff]));
  });

  it('a React Native { uri } part is what expo/fetch rejects', async () => {
    const form = new FormData();
    form.append('file', { uri: 'file:///photo.jpg', name: 'x.jpg', type: 'image/jpeg' } as unknown as Blob);
    await expect(convertFormDataAsync(form)).rejects.toThrow('Unsupported FormDataPart implementation');
  });
});
