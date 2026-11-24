// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, screen, waitFor } from '@testing-library/react-native';
import { useLocalSearchParams } from 'expo-router';

import ReceiptScreen from '@/app/(app)/receipts/[id]';
import SettingsScreen from '@/app/(app)/settings/index';
import * as confirm from '@/components/confirm';
import { fakeApi } from '../test-utils/fakeApi';
import { product, receiptLine, receiptOut } from '../test-utils/fixtures';
import { renderConnected } from '../test-utils/render';
import { resetRouter } from '../test-utils/router';

const params = useLocalSearchParams as jest.Mock;
const CONNECTION = 'GET /api/v1/stores/mercadona/connection';
const PUT = 'PUT /api/v1/stores/mercadona/connection';
const SEARCH = 'GET /api/v1/stores/mercadona/search';
const ADD = 'POST /api/v1/stores/mercadona/products';
const DELETE = 'DELETE /api/v1/stores/mercadona/connection';

// SYNTHETIC store answers.
const disconnected = {
  store_id: 'mercadona', name: 'Mercadona', opt_in: true, notice: 'server notice', notice_accepted_at: null,
  supports_postcode: true, postal_code: null, ready: false,
};
const connected = { ...disconnected, notice_accepted_at: '2026-11-24T18:00:00Z', postal_code: '29003', ready: true };
const found = [
  { store_sku: '111', name: 'Yakisoba sabor soja', brand: 'Marca', package_amount: '90', package_unit: 'g', image_url: null, product_id: null },
  { store_sku: '222', name: 'Fideos soja', brand: null, package_amount: null, package_unit: null, image_url: null, product_id: 41 },
];

beforeEach(() => {
  resetRouter();
  jest.clearAllMocks();
  params.mockReturnValue({ id: '5' });
});

function receiptWithYak() {
  const yak = receiptLine(3, 'YAK SOJA CUP', 100, { status: 'unmatched', search_name: 'yakisoba soja vaso' });
  return receiptOut({ postal_code: '29003', lines: [receiptOut().lines[0], yak] });
}

async function openStoreSearch() {
  await screen.findByText('YAK SOJA CUP');
  await fireEvent.press(screen.getAllByRole('button', { name: 'Cambiar producto' })[1]);
  await fireEvent.press(screen.getByRole('button', { name: 'Buscar en Mercadona' }));
}

describe('searching the receipt store for a missing product', () => {
  it('asks for the notice and the postal code first, then searches with the plain-words name', async () => {
    let state: Record<string, unknown> = disconnected;
    const api = fakeApi({
      'GET /api/v1/receipts/5': receiptWithYak(),
      [CONNECTION]: () => state,
      [PUT]: () => (state = connected),
      [SEARCH]: found,
      [ADD]: product({ id: 90, name: 'Yakisoba sabor soja', store_sku: '111' }),
      'POST /api/v1/receipts/5/confirm': { applied: [], ignored: 0 },
    });
    await renderConnected(<ReceiptScreen />, api.fetchImpl);
    await openStoreSearch();

    // The notice in Spanish and the postal code read from the receipt; nothing sent to the store yet.
    expect(await screen.findByText(/consulta la API no documentada de la tienda online de Mercadona/)).toBeTruthy();
    expect(screen.getByLabelText('Código postal de tu tienda').props.value).toBe('29003');
    expect(screen.getByText('Sacado del ticket: compruébalo.')).toBeTruthy();
    expect(api.called(SEARCH)).toHaveLength(0);

    await fireEvent.press(screen.getByRole('button', { name: 'Acepto y activar Mercadona' }));
    await waitFor(() => expect(api.called(PUT)).toHaveLength(1));
    expect(api.called(PUT)[0].body).toEqual({ postal_code: '29003', accept_notice: true });

    await waitFor(() => expect(api.called(SEARCH)).toHaveLength(1));
    expect(api.called(SEARCH)[0].query).toEqual({ q: 'yakisoba soja vaso' });
    await fireEvent.press(await screen.findByRole('button', { name: 'Yakisoba sabor soja · 90 g' }));
    await waitFor(() => expect(api.called(ADD)).toHaveLength(1));
    expect(api.called(ADD)[0].body).toEqual({ store_sku: '111' });
    expect(await screen.findByText('Seguro · Yakisoba sabor soja')).toBeTruthy();

    await fireEvent.press(screen.getByRole('button', { name: 'Confirmar y añadir' }));
    await waitFor(() => expect(api.called('POST /api/v1/receipts/5/confirm')).toHaveLength(1));
    const lines = (api.called('POST /api/v1/receipts/5/confirm')[0].body as { lines: { line_id: number; product_id?: number }[] }).lines;
    expect(lines.find((l) => l.line_id === 3)?.product_id).toBe(90);
  });

  it('uses a product already in the catalogue without adding it again, and searches only when asked', async () => {
    const api = fakeApi({ 'GET /api/v1/receipts/5': receiptWithYak(), [CONNECTION]: connected, [SEARCH]: found });
    await renderConnected(<ReceiptScreen />, api.fetchImpl);
    await openStoreSearch();
    await waitFor(() => expect(api.called(SEARCH)).toHaveLength(1));

    await fireEvent.changeText(screen.getByLabelText('Qué buscar en Mercadona'), 'fideos soja');
    expect(api.called(SEARCH)).toHaveLength(1); // typing does not reach the store
    await fireEvent.press(screen.getAllByRole('button', { name: 'Buscar en Mercadona' }).at(-1)!);
    await waitFor(() => expect(api.called(SEARCH)).toHaveLength(2));
    expect(api.called(SEARCH)[1].query).toEqual({ q: 'fideos soja' });

    await fireEvent.press(await screen.findByRole('button', { name: 'Fideos soja' }));
    expect(await screen.findByText('Seguro · Fideos soja')).toBeTruthy();
    expect(api.called(ADD)).toHaveLength(0);
  });

  it('says so when the store finds nothing', async () => {
    const api = fakeApi({ 'GET /api/v1/receipts/5': receiptWithYak(), [CONNECTION]: connected, [SEARCH]: [] });
    await renderConnected(<ReceiptScreen />, api.fetchImpl);
    await openStoreSearch();
    expect(await screen.findByText(/No aparece en Mercadona/)).toBeTruthy();
  });
});

describe('the store in settings', () => {
  const household = { id: 1, name: 'Casa', weekly_budget_cents: 6000, currency: 'EUR' };
  const stores = [
    { id: 'mercadona', name: 'Mercadona', country: 'ES', currency: 'EUR', opt_in: true, notice: 'n', attribution: null },
    { id: 'open_prices', name: 'Open Prices', country: null, currency: 'EUR', opt_in: false, notice: null, attribution: null },
  ];

  it('shows where you shop and withdraws the notice after confirming', async () => {
    jest.spyOn(confirm, 'confirmAction').mockResolvedValue(true);
    const api = fakeApi({
      'GET /api/v1/household': household,
      'GET /api/v1/profiles': [],
      'GET /api/v1/stores': stores,
      [CONNECTION]: connected,
      [DELETE]: undefined,
    });
    await renderConnected(<SettingsScreen />, api.fetchImpl);
    expect(await screen.findByText('Mercadona activado · código postal 29003')).toBeTruthy();
    expect(screen.queryByText('Open Prices')).toBeNull(); // only opt-in stores need this
    await fireEvent.press(screen.getByRole('button', { name: 'Desactivar Mercadona' }));
    await waitFor(() => expect(api.called(DELETE)).toHaveLength(1));
  });
});
