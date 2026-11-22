// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, screen, waitFor } from '@testing-library/react-native';
import { Share } from 'react-native';

import ShoppingScreen from '@/app/(app)/shopping';
import * as confirm from '@/components/confirm';
import { shoppingText } from '@/features/shopping/text';
import { fakeApi } from '../test-utils/fakeApi';
import { plan } from '../test-utils/fixtures';
import { renderConnected } from '../test-utils/render';
import { localISODate, mondayOf } from '@/i18n';
import type { Schemas } from '@/api/client';

type List = Schemas['ShoppingListOut'];

const item = (id: number, name: string, extra: Partial<Schemas['ShoppingItemOut']> = {}) =>
  ({ id, product_id: id, name, packs: 2, unit_price_cents: 115, checked: false, alternatives: [], ...extra }) as Schemas['ShoppingItemOut'];

const mercadona: List = {
  store_id: 'mercadona', total_cents: 1250, items: [item(3, 'Arroz')], unavailable: [],
};
const dia: List = {
  store_id: 'dia',
  total_cents: 990,
  items: [
    item(8, 'Arroz largo', {
      replaces: 'Arroz', replaces_product_id: 3, unit_price_cents: 99,
      alternatives: [
        { product_id: 9, name: 'Arroz integral', packs: 1, price_cents: 160, cost_cents: 160, extra_cost_cents: 62, kcal_diff_pct: '2.9', protein_diff_pct: null },
        { product_id: 10, name: 'Arroz bomba', packs: 2, price_cents: 90, cost_cents: 180, extra_cost_cents: 0, kcal_diff_pct: '-1.5', protein_diff_pct: null },
      ],
    }),
  ],
  unavailable: [{ product_id: 5, name: 'Cacahuetes', amount: '300', unit: 'g', reason: 'not_sold' }],
};
const stores = [
  { store_id: 'mercadona', products: 25, priced: 25 },
  { store_id: 'dia', products: 10, priced: 10 },
];

function server(extra: Record<string, unknown> = {}) {
  return fakeApi({
    'GET /api/v1/plans': plan(mondayOf(localISODate()), []),
    'GET /api/v1/catalog/stores': stores,
    'GET /api/v1/plans/7/shopping-list': mercadona,
    'POST /api/v1/plans/7/shopping-list': ({ body }: { body: { store_id: string } }) => (body.store_id === 'dia' ? dia : mercadona),
    ...extra,
  });
}

beforeEach(() => {
  jest.restoreAllMocks();
  jest.spyOn(confirm, 'confirmAction').mockResolvedValue(true);
});

describe('shopping list', () => {
  it('shows the list of the plan store with totals and progress', async () => {
    await renderConnected(<ShoppingScreen />, server().fetchImpl);
    expect(await screen.findByText('Tienda: mercadona')).toBeTruthy();
    expect(screen.getByText('Total: 12,50 €')).toBeTruthy();
    expect(screen.getByText('0 de 1 marcados')).toBeTruthy();
    expect(screen.getByText('1,15 € cada uno')).toBeTruthy();
  });

  it('switches store, building that store list, with substitutes, alternatives and what it does not sell', async () => {
    const api = server();
    await renderConnected(<ShoppingScreen />, api.fetchImpl);
    await screen.findByText('Tienda: mercadona');
    await fireEvent.press(screen.getByRole('radio', { name: 'dia' }));

    expect(await screen.findByText('Tienda: dia')).toBeTruthy();
    expect(screen.getByText('Total: 9,90 €')).toBeTruthy();
    expect(screen.getByText('En lugar de Arroz')).toBeTruthy();
    expect(api.called('POST /api/v1/plans/7/shopping-list').at(-1)?.body).toEqual({ store_id: 'dia', refresh: false });

    expect(screen.queryByText(/Arroz integral/)).toBeNull(); // alternatives start collapsed
    await fireEvent.press(screen.getByRole('button', { name: 'Ver alternativas' }));
    expect(screen.getByText('Arroz integral: +0,62 € · +2,9 % de calorías')).toBeTruthy();
    expect(screen.getByText('Arroz bomba: mismo precio · -1,5 % de calorías')).toBeTruthy();

    expect(screen.getByText('No disponible en esta tienda')).toBeTruthy();
    expect(screen.getByText(/Cacahuetes \(300 g\)/)).toBeTruthy();
    await fireEvent.press(screen.getByRole('radio', { name: 'mercadona' }));
    expect(await screen.findByText('Tienda: mercadona')).toBeTruthy();
  });

  it('does not show a store selector when there is only one store', async () => {
    const api = server({ 'GET /api/v1/catalog/stores': [stores[0]] });
    await renderConnected(<ShoppingScreen />, api.fetchImpl);
    await screen.findByText('Tienda: mercadona');
    expect(screen.queryByRole('radio', { name: 'dia' })).toBeNull();
  });

  it('explains when there is no plan this week', async () => {
    await renderConnected(<ShoppingScreen />, fakeApi({ 'GET /api/v1/plans': null }).fetchImpl);
    expect(await screen.findByText('No hay lista de la compra')).toBeTruthy();
  });
});

describe('ticking an item', () => {
  const tick = (checked: boolean, direction: 'added' | 'removed') => ({
    ...item(3, 'Arroz', { checked }),
    pantry_effect: { product_id: 3, name: 'Arroz', amount: '2000', unit: 'g', direction },
  });

  it('warns the first time that it adds to the pantry, then says what changed', async () => {
    let checked = false;
    const current = () => ({ ...mercadona, items: [item(3, 'Arroz', { checked })] });
    const api = server({
      'GET /api/v1/plans/7/shopping-list': current,
      'POST /api/v1/plans/7/shopping-list': current,
      'PATCH /api/v1/shopping-items/3': ({ body }: { body: { checked: boolean } }) => {
        checked = body.checked;
        return tick(checked, checked ? 'added' : 'removed');
      },
    });
    await renderConnected(<ShoppingScreen />, api.fetchImpl);
    expect(await screen.findByText(/Al marcar un producto se añade a tu despensa/)).toBeTruthy();

    await fireEvent.press(screen.getByRole('checkbox', { name: '2 × Arroz' }));
    expect(confirm.confirmAction).toHaveBeenCalledTimes(1);
    expect(await screen.findByText('Añadido a la despensa: Arroz (2 kg)')).toBeTruthy();
    expect(screen.getByText('1 de 1 marcados')).toBeTruthy();
    expect(api.called('PATCH /api/v1/shopping-items/3')[0].body).toEqual({ checked: true });

    await fireEvent.press(screen.getByRole('checkbox', { name: '2 × Arroz' }));
    expect(await screen.findByText('Quitado de la despensa: Arroz (2 kg)')).toBeTruthy();
    expect(confirm.confirmAction).toHaveBeenCalledTimes(1); // asked only once
  });

  it('does nothing when the person declines the first-time notice', async () => {
    jest.spyOn(confirm, 'confirmAction').mockResolvedValue(false);
    const api = server();
    await renderConnected(<ShoppingScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('checkbox', { name: '2 × Arroz' }));
    await waitFor(() => expect(confirm.confirmAction).toHaveBeenCalled());
    expect(api.called('PATCH /api/v1/shopping-items/3')).toHaveLength(0);
  });
});

describe('sharing', () => {
  it('shares the list as plain text', async () => {
    const share = jest.spyOn(Share, 'share').mockResolvedValue({ action: 'sharedAction', activityType: undefined });
    await renderConnected(<ShoppingScreen />, server().fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Compartir lista' }));
    expect(share).toHaveBeenCalledWith({ message: shoppingText(mercadona) });
  });

  it('writes one line per item, with ticks, substitutes and what is unavailable', () => {
    const text = shoppingText({ ...dia, items: [{ ...dia.items[0], checked: true }, item(4, 'Leche', { unit_price_cents: null })] });
    expect(text.replace(/\u00a0/g, ' ').split('\n')).toEqual([
      'Lista de la compra · dia',
      'Total: 9,90 €',
      '',
      '☑ 2 × Arroz largo (0,99 €)',
      '   en lugar de Arroz',
      '☐ 2 × Leche (?)',
      '',
      'No disponible en esta tienda:',
      '- Cacahuetes (300 g)',
    ]);
  });
});
