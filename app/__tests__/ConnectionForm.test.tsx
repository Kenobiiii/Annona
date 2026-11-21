// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, screen, waitFor } from '@testing-library/react-native';
import * as SecureStore from 'expo-secure-store';

import { ConnectionForm } from '@/features/connection/ConnectionForm';
import { apiError, fakeApi } from '../test-utils/fakeApi';
import { renderFirstRun } from '../test-utils/render';

const store = () => (SecureStore as unknown as { __data: Map<string, string> }).__data;

async function fill(url: string, token: string) {
  await fireEvent.changeText(screen.getByLabelText('Dirección del servidor'), url);
  await fireEvent.changeText(screen.getByLabelText('Token'), token);
}

it('validates before saving and shows what is wrong', async () => {
  await renderFirstRun(<ConnectionForm />);
  await fireEvent.press(screen.getByRole('button', { name: 'Guardar y continuar' }));
  expect(await screen.findByText('Escribe la dirección del servidor.')).toBeTruthy();
  expect(screen.getByText('Escribe el token.')).toBeTruthy();
  expect(store().size).toBe(0);
});

it('warns about unencrypted http', async () => {
  await renderFirstRun(<ConnectionForm />);
  await fill('192.168.1.20:8000', 'abc');
  expect(await screen.findByText(/no está cifrada/)).toBeTruthy();
});

it('tests the connection and reports the server version', async () => {
  const server = fakeApi({ 'GET /health': { status: 'ok', version: '0.4.0' }, 'GET /api/v1/stores': [] });
  await renderFirstRun(<ConnectionForm fetchImpl={server.fetchImpl} />);
  await fill('192.168.1.20:8000', 'abc');
  await fireEvent.press(screen.getByRole('button', { name: 'Probar conexión' }));
  expect(await screen.findByText('Conectado: Annona 0.4.0')).toBeTruthy();
  expect(server.calls[0].path).toBe('/health');
});

it('tells the user when the token is wrong', async () => {
  const server = fakeApi({
    'GET /health': { status: 'ok', version: '0.4.0' },
    'GET /api/v1/stores': () => apiError(401, 'unauthorized', 'wrong'),
  });
  await renderFirstRun(<ConnectionForm fetchImpl={server.fetchImpl} />);
  await fill('192.168.1.20:8000', 'bad');
  await fireEvent.press(screen.getByRole('button', { name: 'Probar conexión' }));
  expect(await screen.findByText(/no acepta el token/)).toBeTruthy();
});

it('saves a normalised address and token, then continues', async () => {
  const onSaved = jest.fn();
  await renderFirstRun(<ConnectionForm onSaved={onSaved} />);
  await fill(' 192.168.1.20:8000/ ', ' abc ');
  await fireEvent.press(screen.getByRole('button', { name: 'Guardar y continuar' }));
  await waitFor(() => expect(onSaved).toHaveBeenCalled());
  expect(store().get('annona.server_url')).toBe('http://192.168.1.20:8000');
  expect(store().get('annona.token')).toBe('abc');
});
