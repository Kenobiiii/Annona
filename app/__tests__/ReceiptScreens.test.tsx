// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, screen, waitFor } from '@testing-library/react-native';
import * as ImageManipulator from 'expo-image-manipulator';
import * as ImagePicker from 'expo-image-picker';
import { useLocalSearchParams } from 'expo-router';

import NewReceiptScreen from '@/app/(app)/receipts/new';
import ReceiptScreen from '@/app/(app)/receipts/[id]';
import * as confirm from '@/components/confirm';
import { nameFromReceipt } from '@/features/receipts/LineCard';
import { apiError, fakeApi } from '../test-utils/fakeApi';
import { product, receiptLine, receiptOut } from '../test-utils/fixtures';
import { renderConnected } from '../test-utils/render';
import { resetRouter, router } from '../test-utils/router';

jest.mock('@/features/receipts/upload', () => ({ buildReceiptForm: jest.fn(async () => 'FORM') }));

const params = useLocalSearchParams as jest.Mock;
const picker = ImagePicker as unknown as Record<string, jest.Mock>;
const manipulator = (ImageManipulator as unknown as { __context: { resize: jest.Mock } }).__context;
const UPLOAD = 'POST /api/v1/receipts';
const page = (items: unknown[]) => ({ items, page: 1, size: 30, total: items.length });

beforeEach(() => {
  resetRouter();
  jest.clearAllMocks();
  jest.spyOn(confirm, 'confirmAction').mockResolvedValue(true);
});

describe('capturing a receipt', () => {
  it('tells the person the photo goes to the AI, shrinks it, uploads it and opens the review', async () => {
    const api = fakeApi({ [UPLOAD]: receiptOut() });
    await renderConnected(<NewReceiptScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Hacer una foto' }));

    await waitFor(() => expect(router.replace).toHaveBeenCalledWith({ pathname: '/receipts/[id]', params: { id: '5' } }));
    expect(confirm.confirmAction).toHaveBeenCalledWith(
      'La foto se envía a la IA',
      expect.stringContaining('proveedor de IA'),
      'Entendido',
      'Cancelar',
    );
    expect(picker.requestCameraPermissionsAsync).toHaveBeenCalled();
    expect(manipulator.resize).toHaveBeenCalledWith({ width: 1600 }); // a 3000 px photo is shrunk
    expect(api.called(UPLOAD)).toHaveLength(1);
  });

  it('asks about the AI only the first time', async () => {
    await renderConnected(<NewReceiptScreen />, fakeApi({ [UPLOAD]: receiptOut() }).fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Elegir de la galería' }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledTimes(1));
    await fireEvent.press(screen.getByRole('button', { name: 'Hacer una foto' }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledTimes(2));
    expect(confirm.confirmAction).toHaveBeenCalledTimes(1);
    expect(picker.launchImageLibraryAsync).toHaveBeenCalledTimes(1);
  });

  it('does not take or send a photo when the person declines the notice', async () => {
    jest.spyOn(confirm, 'confirmAction').mockResolvedValue(false);
    const api = fakeApi({ [UPLOAD]: receiptOut() });
    await renderConnected(<NewReceiptScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Hacer una foto' }));
    await waitFor(() => expect(confirm.confirmAction).toHaveBeenCalled());
    expect(picker.launchCameraAsync).not.toHaveBeenCalled();
    expect(api.called(UPLOAD)).toHaveLength(0);
  });

  it('explains a denied camera permission and sends nothing', async () => {
    picker.requestCameraPermissionsAsync.mockResolvedValueOnce({ granted: false });
    const api = fakeApi({ [UPLOAD]: receiptOut() });
    await renderConnected(<NewReceiptScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Hacer una foto' }));
    expect(await screen.findByText(/hace falta permiso para usar la cámara/)).toBeTruthy();
    expect(api.called(UPLOAD)).toHaveLength(0);
  });

  it('does nothing when the person cancels the picker', async () => {
    picker.launchCameraAsync.mockResolvedValueOnce({ canceled: true, assets: [] });
    const api = fakeApi({ [UPLOAD]: receiptOut() });
    await renderConnected(<NewReceiptScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Hacer una foto' }));
    await waitFor(() => expect(picker.launchCameraAsync).toHaveBeenCalled());
    expect(api.called(UPLOAD)).toHaveLength(0);
  });

  it('shows that it is reading, then a clear message when the image is refused', async () => {
    let release: (value: unknown) => void = () => {};
    const slow = new Promise((resolve) => (release = resolve));
    const api = fakeApi({ [UPLOAD]: async () => (await slow, apiError(422, 'bad_image', 'only JPEG...')) });
    await renderConnected(<NewReceiptScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Hacer una foto' }));
    expect(await screen.findByText('Leyendo el ticket…')).toBeTruthy();
    release(null);
    expect(await screen.findByText(/Esa imagen no vale/)).toBeTruthy();
    expect(router.replace).not.toHaveBeenCalled();
  });
});

describe('reviewing a receipt', () => {
  beforeEach(() => params.mockReturnValue({ id: '5' }));
  const GET = 'GET /api/v1/receipts/5';
  const CONFIRM = 'POST /api/v1/receipts/5/confirm';
  const switchFor = (n: number) => screen.getAllByLabelText('Añadir a la despensa')[n];

  it('shows the summary and that the lines add up to the total', async () => {
    await renderConnected(<ReceiptScreen />, fakeApi({ [GET]: receiptOut() }).fetchImpl);
    expect(await screen.findByText(/mercadona · .* · total 7,23 €/)).toBeTruthy();
    expect(screen.getByText('La suma de las líneas coincide con el total del ticket (7,23 €).')).toBeTruthy();
    expect(screen.getByText('2 de 4 líneas se añadirán')).toBeTruthy();
  });

  it('warns when the lines do not add up, and when the total could not be read', async () => {
    const bad = receiptOut({ total_matches: false, lines_total_cents: 700 });
    await renderConnected(<ReceiptScreen />, fakeApi({ [GET]: bad }).fetchImpl);
    expect(await screen.findByText(/Las líneas suman 7,00 € y el ticket dice 7,23 €/)).toBeTruthy();
  });

  it('says so when the total was unreadable', async () => {
    const unknown = receiptOut({ total_matches: null, total_cents: null });
    await renderConnected(<ReceiptScreen />, fakeApi({ [GET]: unknown }).fetchImpl);
    expect(await screen.findByText(/No se ha podido leer el total/)).toBeTruthy();
  });

  it('pre-selects only the confident lines; doubtful and unmatched ones start off', async () => {
    await renderConnected(<ReceiptScreen />, fakeApi({ [GET]: receiptOut() }).fetchImpl);
    await screen.findByText('ARROZ REDONDO 1KG');
    expect(switchFor(0).props.value).toBe(true); // rice: 97 %
    expect(switchFor(1).props.value).toBe(false); // milk: 70 %, doubtful
    expect(switchFor(2).props.value).toBe(false); // plastic bag: no product
    expect(switchFor(3).props.value).toBe(true); // yogurt: 91 %
    expect(screen.getByText('Seguro · Arroz redondo Hacendado (97 %)')).toBeTruthy();
    expect(screen.getByText('Dudoso · Leche entera Hacendado (70 %)')).toBeTruthy();
    expect(screen.getByText('Sin emparejar')).toBeTruthy();
  });

  it('never applies a doubtful or unmatched line the person did not choose', async () => {
    const api = fakeApi({ [GET]: receiptOut(), [CONFIRM]: { applied: [], ignored: 4 } });
    await renderConnected(<ReceiptScreen />, api.fetchImpl);
    await screen.findByText('ARROZ REDONDO 1KG');
    await fireEvent.changeText(screen.getByLabelText('Cantidad comprada'), '375'); // yogurt: unknown pack size
    await fireEvent.press(screen.getByRole('button', { name: 'Confirmar y añadir' }));
    await waitFor(() => expect(api.called(CONFIRM)).toHaveLength(1));
    expect(api.called(CONFIRM)[0].body).toEqual({
      lines: [
        { line_id: 1, product_id: 10, ignore: false },
        { line_id: 2, ignore: true }, // doubtful: not applied
        { line_id: 3, ignore: true }, // no product: not applied
        { line_id: 4, product_id: 13, ignore: false, amount: 375, unit: 'g' },
      ],
    });
  });

  it('applies a doubtful line only after the person switches it on', async () => {
    const api = fakeApi({ [GET]: receiptOut(), [CONFIRM]: { applied: [], ignored: 0 } });
    await renderConnected(<ReceiptScreen />, api.fetchImpl);
    await screen.findByText('ARROZ REDONDO 1KG');
    await fireEvent(switchFor(1), 'valueChange', true);
    await fireEvent.changeText(screen.getByLabelText('Cantidad comprada'), '375');
    await fireEvent.press(screen.getByRole('button', { name: 'Confirmar y añadir' }));
    await waitFor(() => expect(api.called(CONFIRM)).toHaveLength(1));
    const lines = (api.called(CONFIRM)[0].body as { lines: { line_id: number; ignore: boolean }[] }).lines;
    expect(lines.find((l) => l.line_id === 2)).toMatchObject({ product_id: 11, ignore: false });
  });

  it('lets the person pick another product with the search or the suggested alternatives', async () => {
    const api = fakeApi({
      [GET]: receiptOut(),
      'GET /api/v1/products': page([product({ id: 77, name: 'Leche de avena' })]),
      [CONFIRM]: { applied: [], ignored: 0 },
    });
    await renderConnected(<ReceiptScreen />, api.fetchImpl);
    await screen.findByText('LECHE');
    await fireEvent.press(screen.getAllByRole('button', { name: 'Cambiar producto' })[1]);
    await fireEvent.press(screen.getByRole('checkbox', { name: 'Leche semidesnatada Hacendado' }));
    expect(switchFor(1).props.value).toBe(true); // picking a product is an explicit choice
    expect(screen.getByText('Seguro · Leche semidesnatada Hacendado')).toBeTruthy();

    await fireEvent.press(screen.getAllByRole('button', { name: 'Cambiar producto' })[1]);
    await fireEvent.changeText(screen.getByLabelText('Buscar producto'), 'avena');
    await fireEvent.press(await screen.findByRole('button', { name: 'Leche de avena' }));
    expect(screen.getByText('Seguro · Leche de avena')).toBeTruthy();
    await fireEvent.changeText(screen.getByLabelText('Cantidad comprada'), '1000');
    await fireEvent.press(screen.getByRole('button', { name: 'Confirmar y añadir' }));
    await waitFor(() => expect(api.called(CONFIRM)).toHaveLength(1));
    const lines = (api.called(CONFIRM)[0].body as { lines: { line_id: number; product_id?: number }[] }).lines;
    expect(lines.find((l) => l.line_id === 2)?.product_id).toBe(77);
  });

  it('creates a product the catalogue does not have and uses it for the line', async () => {
    const created = product({ id: 90, name: 'Bolsa plastico', store_id: null, store_sku: null, nutrition: null });
    const api = fakeApi({
      [GET]: receiptOut(),
      'POST /api/v1/products': created,
      [CONFIRM]: { applied: [], ignored: 0 },
    });
    await renderConnected(<ReceiptScreen />, api.fetchImpl);
    await screen.findByText('BOLSA PLASTICO');
    await fireEvent.press(screen.getAllByRole('button', { name: 'Cambiar producto' })[2]);
    await fireEvent.press(screen.getByRole('button', { name: 'No está: crear producto nuevo' }));
    expect(screen.getByLabelText('Nombre del producto').props.value).toBe('Bolsa plastico');
    expect(screen.getByText(/quedan sin datos hasta que los completes/)).toBeTruthy(); // nothing invented
    await fireEvent.press(screen.getByRole('radio', { name: 'Otros' }));
    await fireEvent.changeText(screen.getByLabelText('Tamaño del envase (opcional)'), '1');
    const units = screen.getAllByRole('radio', { name: 'ud.' });
    await fireEvent.press(units[units.length - 2]); // the last one is the yogurt line's amount unit
    await fireEvent.press(screen.getByRole('button', { name: 'Crear y usar en esta línea' }));

    await waitFor(() => expect(api.called('POST /api/v1/products')).toHaveLength(1));
    expect(api.called('POST /api/v1/products')[0].body).toEqual({
      name: 'Bolsa plastico', category: 'other', package_amount: 1, package_unit: 'unit',
    });
    expect(await screen.findByText('Seguro · Bolsa plastico')).toBeTruthy();
    expect(switchFor(2).props.value).toBe(true);
  });

  it('does not create a product without a name or with a wrong pack size', async () => {
    const api = fakeApi({ [GET]: receiptOut() });
    await renderConnected(<ReceiptScreen />, api.fetchImpl);
    await screen.findByText('BOLSA PLASTICO');
    await fireEvent.press(screen.getAllByRole('button', { name: 'Cambiar producto' })[2]);
    await fireEvent.press(screen.getByRole('button', { name: 'No está: crear producto nuevo' }));
    const submit = () => screen.getByRole('button', { name: 'Crear y usar en esta línea' });
    await fireEvent.changeText(screen.getByLabelText('Tamaño del envase (opcional)'), 'abc');
    expect(submit().props.accessibilityState?.disabled).toBe(true);
    await fireEvent.changeText(screen.getByLabelText('Tamaño del envase (opcional)'), '');
    await fireEvent.changeText(screen.getByLabelText('Nombre del producto'), '  ');
    expect(submit().props.accessibilityState?.disabled).toBe(true);
    await fireEvent.press(submit());
    expect(api.called('POST /api/v1/products')).toHaveLength(0);
  });

  it('asks for the amount the server could not know and keeps the review open', async () => {
    const api = fakeApi({
      [GET]: receiptOut({ lines: receiptOut().lines.filter((l) => l.id === 1 || l.id === 2) }),
      [CONFIRM]: apiError(422, 'amount_required', 'say how much', [1]),
    });
    await renderConnected(<ReceiptScreen />, api.fetchImpl);
    await screen.findByText('ARROZ REDONDO 1KG');
    expect(screen.queryByLabelText('Cantidad comprada')).toBeNull(); // known amount: no field
    await fireEvent.press(screen.getByRole('button', { name: 'Confirmar y añadir' }));
    expect(await screen.findByText('Indica la cantidad en las líneas marcadas.')).toBeTruthy();
    expect(screen.getByLabelText('Cantidad comprada')).toBeTruthy();
  });

  it('lists what changed after confirming and leads to the pantry', async () => {
    const api = fakeApi({
      [GET]: receiptOut(),
      [CONFIRM]: {
        applied: [{ line_id: 1, product_id: 10, name: 'Arroz redondo Hacendado', amount: '1000', unit: 'g', price_cents: 115, notes: [] }],
        ignored: 3,
      },
    });
    await renderConnected(<ReceiptScreen />, api.fetchImpl);
    await screen.findByText('ARROZ REDONDO 1KG');
    await fireEvent.changeText(screen.getByLabelText('Cantidad comprada'), '375');
    await fireEvent.press(screen.getByRole('button', { name: 'Confirmar y añadir' }));
    expect(await screen.findByText('Despensa actualizada')).toBeTruthy();
    expect(screen.getByText('Arroz redondo Hacendado: 1 kg · 1,15 €')).toBeTruthy();
    await fireEvent.press(screen.getByRole('button', { name: 'Ver la despensa' }));
    expect(router.replace).toHaveBeenCalledWith('/products');
  });

  it('discards a scan after confirming', async () => {
    const api = fakeApi({ [GET]: receiptOut(), 'POST /api/v1/receipts/5/discard': () => undefined });
    await renderConnected(<ReceiptScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Descartar ticket' }));
    await waitFor(() => expect(api.called('POST /api/v1/receipts/5/discard')).toHaveLength(1));
    expect(confirm.confirmAction).toHaveBeenCalled();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith('/'));
  });

  it('shows an already closed receipt as such, with nothing to confirm', async () => {
    const api = fakeApi({ [GET]: receiptOut({ status: 'confirmed' }) });
    await renderConnected(<ReceiptScreen />, api.fetchImpl);
    expect(await screen.findByText('Este ticket ya se confirmó.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Confirmar y añadir' })).toBeNull();
  });

  it('warns about adding the same purchase twice (shopping list and receipt)', async () => {
    await renderConnected(<ReceiptScreen />, fakeApi({ [GET]: receiptOut() }).fetchImpl);
    expect(await screen.findByText(/no la añadas también aquí/)).toBeTruthy();
    expect(receiptLine).toBeDefined();
  });
});

describe('nameFromReceipt', () => {
  it('turns a printed line into a readable name', () => {
    expect(nameFromReceipt('1 TOMATE TRITURADO')).toBe('Tomate triturado');
    expect(nameFromReceipt('12 HUEVOS GRANDES-L')).toBe('Huevos grandes-l');
    expect(nameFromReceipt('MAC-CHEESE')).toBe('Mac-cheese');
  });
});
