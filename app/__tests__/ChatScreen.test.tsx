// SPDX-License-Identifier: AGPL-3.0-or-later
import { act, fireEvent, screen, waitFor } from '@testing-library/react-native';

import * as chatApi from '@/api/chat';
import { ApiError } from '@/api/errors';
import ChatScreen from '@/app/(app)/chat';
import * as confirm from '@/components/confirm';
import { apiError, fakeApi } from '../test-utils/fakeApi';
import { renderConnected } from '../test-utils/render';

jest.mock('@/api/chat', () => ({ ...jest.requireActual('@/api/chat'), streamChat: jest.fn() }));

const stream = chatApi.streamChat as unknown as jest.Mock;
type Event = chatApi.ChatEvent;

function events(...list: Event[]) {
  return async function* () {
    for (const e of list) yield e;
  };
}
const done = (text = ''): Event => ({ type: 'done', text, stopped: 'answered', iterations: 1, proposals: [] });
const text = (delta: string): Event => ({ type: 'text', delta });

beforeEach(() => {
  jest.clearAllMocks();
  jest.spyOn(confirm, 'confirmAction').mockResolvedValue(true);
});

async function ask(message: string) {
  await fireEvent.changeText(await screen.findByLabelText('Escribe tu mensaje'), message);
  await fireEvent.press(screen.getByRole('button', { name: 'Enviar' }));
}

describe('chatting', () => {
  it('tells the person the data goes to the AI the first time, then streams the answer', async () => {
    stream.mockImplementationOnce(() =>
      events(
        { type: 'tool_start', id: 'a', name: 'get_pantry' },
        { type: 'tool_end', id: 'a', name: 'get_pantry', ok: true, summary: 'ok' },
        text('Tienes '),
        text('arroz.'),
        done('Tienes arroz.'),
      )(),
    );
    await renderConnected(<ChatScreen />, fakeApi({}).fetchImpl);
    await ask('¿qué tengo?');
    expect(await screen.findByText('Tienes arroz.')).toBeTruthy();
    expect(screen.getByText('¿qué tengo?')).toBeTruthy();
    expect(confirm.confirmAction).toHaveBeenCalledWith('El chat envía datos a la IA', expect.stringContaining('proveedor de IA'), 'Entendido', 'Cancelar');
    expect(stream.mock.calls[0][1]).toEqual({ message: '¿qué tengo?', history: [], tier: 'small' });
  });

  it('shows what is being looked up while it works', async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => (release = resolve));
    stream.mockImplementationOnce(async function* () {
      yield { type: 'tool_start', id: 'a', name: 'get_pantry' } as Event;
      await gate;
      yield { type: 'tool_end', id: 'a', name: 'get_pantry', ok: true, summary: 'ok' } as Event;
      yield text('Listo.');
      yield done('Listo.');
    });
    await renderConnected(<ChatScreen />, fakeApi({}).fetchImpl);
    await ask('mira');
    expect(await screen.findByText('Mirando tu despensa…')).toBeTruthy();
    await act(async () => release());
    expect(await screen.findByText('Listo.')).toBeTruthy();
    expect(screen.queryByText('Mirando tu despensa…')).toBeNull();
  });

  it('asks about the data only once and sends the earlier messages as history', async () => {
    stream.mockImplementationOnce(() => events(text('Uno.'), done('Uno.'))());
    stream.mockImplementationOnce(() => events(text('Dos.'), done('Dos.'))());
    await renderConnected(<ChatScreen />, fakeApi({}).fetchImpl);
    await ask('primero');
    await screen.findByText('Uno.');
    await ask('segundo');
    await screen.findByText('Dos.');
    expect(confirm.confirmAction).toHaveBeenCalledTimes(1);
    expect(stream.mock.calls[1][1].history).toEqual([
      { role: 'user', text: 'primero' },
      { role: 'assistant', text: 'Uno.' },
    ]);
  });

  it('uses the larger model only when the person asks for it', async () => {
    stream.mockImplementation(() => events(text('ok'), done('ok'))());
    await renderConnected(<ChatScreen />, fakeApi({}).fetchImpl);
    await fireEvent(await screen.findByLabelText(/Respuesta más cuidadosa/), 'valueChange', true);
    await ask('piénsalo bien');
    await screen.findByText('ok');
    expect(stream.mock.calls[0][1].tier).toBe('large');
  });

  it('sends nothing when the person declines the notice', async () => {
    jest.spyOn(confirm, 'confirmAction').mockResolvedValue(false);
    await renderConnected(<ChatScreen />, fakeApi({}).fetchImpl);
    await ask('hola');
    await waitFor(() => expect(confirm.confirmAction).toHaveBeenCalled());
    expect(stream).not.toHaveBeenCalled();
  });

  it('shows an error when the answer cannot be completed, and a note when a limit stopped it', async () => {
    stream.mockImplementationOnce(() => events(text('Parcial'), { type: 'notice', code: 'limit' }, done())());
    stream.mockImplementationOnce(() => events({ type: 'error', message: 'ProviderError: down' })());
    stream.mockImplementationOnce(async function* () {
      throw new ApiError(0, 'network', 'Network request failed');
    });
    await renderConnected(<ChatScreen />, fakeApi({}).fetchImpl);
    await ask('uno');
    expect(await screen.findByText(/Me detuve al llegar al límite de pasos/)).toBeTruthy();
    await ask('dos');
    expect(await screen.findByText(/No se pudo completar la respuesta: ProviderError: down/)).toBeTruthy();
    await ask('tres');
    expect(await screen.findByText(/No se pudo completar la respuesta: Network request failed/)).toBeTruthy();
  });

  it('stops the answer and starts a new conversation', async () => {
    let signal: AbortSignal | undefined;
    stream.mockImplementationOnce(async function* (_c: unknown, _r: unknown, s?: AbortSignal) {
      signal = s;
      yield text('Empiezo…');
      await new Promise((resolve) => s?.addEventListener('abort', resolve));
      const error = new Error('aborted');
      error.name = 'AbortError';
      throw error;
    });
    await renderConnected(<ChatScreen />, fakeApi({}).fetchImpl);
    await ask('algo largo');
    await fireEvent.press(await screen.findByRole('button', { name: 'Parar' }));
    await waitFor(() => expect(signal?.aborted).toBe(true));
    expect(screen.queryByText(/No se pudo completar/)).toBeNull(); // a stop is not an error
    await fireEvent.press(await screen.findByRole('button', { name: 'Nueva conversación' }));
    expect(screen.queryByText('algo largo')).toBeNull();
  });
});

describe('proposed changes', () => {
  const proposal = (): Event => ({ type: 'action', id: 7, tool: 'update_pantry', summary: 'Despensa: añadir 500 g de Arroz' });

  async function withProposal(routes: Record<string, unknown>) {
    stream.mockImplementationOnce(() => events(text('Te lo propongo.'), proposal(), done())());
    const api = fakeApi(routes);
    await renderConnected(<ChatScreen />, api.fetchImpl);
    await ask('apunta 500 g de arroz');
    expect(await screen.findByText('Despensa: añadir 500 g de Arroz')).toBeTruthy();
    return api;
  }

  it('shows the change and says nothing happens until it is confirmed', async () => {
    const api = await withProposal({});
    expect(screen.getByText('No se cambia nada hasta que lo confirmes.')).toBeTruthy();
    expect(api.calls.filter((c) => c.path.includes('/chat/actions'))).toHaveLength(0);
  });

  it('applies the change only when the person presses Confirm', async () => {
    const api = await withProposal({ 'POST /api/v1/chat/actions/7/confirm': { id: 7, tool: 'update_pantry', summary: 's', status: 'confirmed', result: {} } });
    await fireEvent.press(screen.getByRole('button', { name: 'Confirmar' }));
    expect(await screen.findByText('Hecho.')).toBeTruthy();
    expect(api.called('POST /api/v1/chat/actions/7/confirm')).toHaveLength(1);
    expect(screen.queryByRole('button', { name: 'Confirmar' })).toBeNull();
  });

  it('cancels without changing anything', async () => {
    const api = await withProposal({ 'POST /api/v1/chat/actions/7/cancel': { id: 7, tool: 'update_pantry', summary: 's', status: 'cancelled' } });
    await fireEvent.press(screen.getByRole('button', { name: 'Cancelar' }));
    expect(await screen.findByText('Cancelado: no se ha cambiado nada.')).toBeTruthy();
    expect(api.called('POST /api/v1/chat/actions/7/confirm')).toHaveLength(0);
  });

  it('shows why a confirmed change could not be made', async () => {
    await withProposal({ 'POST /api/v1/chat/actions/7/confirm': { id: 7, tool: 'update_pantry', summary: 's', status: 'failed', result: { error: 'product 99 does not exist' } } });
    await fireEvent.press(screen.getByRole('button', { name: 'Confirmar' }));
    expect(await screen.findByText('No se pudo hacer: product 99 does not exist')).toBeTruthy();
  });

  it('treats an already resolved change as closed, not as a crash', async () => {
    await withProposal({ 'POST /api/v1/chat/actions/7/confirm': apiError(409, 'action_closed', 'already confirmed') });
    await fireEvent.press(screen.getByRole('button', { name: 'Confirmar' }));
    expect(await screen.findByText('Cancelado: no se ha cambiado nada.')).toBeTruthy();
  });
});

it('does not leave a lookup "in progress" when the stream breaks', async () => {
  stream.mockImplementationOnce(async function* () {
    yield { type: 'tool_start', id: 'a', name: 'get_pantry' } as Event;
    throw new Error('connection lost');
  });
  await renderConnected(<ChatScreen />, fakeApi({}).fetchImpl);
  await ask('mira');
  expect(await screen.findByText(/No se pudo completar la respuesta: connection lost/)).toBeTruthy();
  expect(screen.queryByText('Mirando tu despensa…')).toBeNull();
});
