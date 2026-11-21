// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, screen } from '@testing-library/react-native';
import { useLocalSearchParams } from 'expo-router';

import ProductScreen from '@/app/(app)/products/[id]';
import ProductsScreen from '@/app/(app)/products/index';
import { fakeApi } from '../test-utils/fakeApi';
import { pantryItem, product } from '../test-utils/fixtures';
import { renderConnected } from '../test-utils/render';
import { resetRouter, router } from '../test-utils/router';

const params = useLocalSearchParams as jest.Mock;
const page = (items: unknown[]) => ({ items, page: 1, size: 200, total: items.length });

beforeEach(() => resetRouter());

describe('pantry', () => {
  it('groups the pantry by category with formatted amounts', async () => {
    const server = fakeApi({
      'GET /api/v1/pantry': page([
        pantryItem(1, 5, 'Arroz redondo', 'grains', '1000.0'),
        pantryItem(2, 6, 'Lenteja cocida', 'legumes', '400', 'g', '2026-11-30'),
        pantryItem(3, 7, 'Pasta', 'grains', '500'),
      ]),
    });
    await renderConnected(<ProductsScreen />, server.fetchImpl);
    expect(await screen.findByText('Cereales, arroz y pasta')).toBeTruthy();
    expect(screen.getByText('Legumbres')).toBeTruthy();
    expect(screen.getByText('1 kg')).toBeTruthy();
    expect(screen.getByText(/caduca el/)).toBeTruthy();
    await fireEvent.press(screen.getByRole('button', { name: 'Lenteja cocida, 400 g' }));
    expect(router.push).toHaveBeenCalledWith('/products/6');
  });

  it('invites to search when the pantry is empty', async () => {
    await renderConnected(<ProductsScreen />, fakeApi({ 'GET /api/v1/pantry': page([]) }).fetchImpl);
    expect(await screen.findByText('Tu despensa está vacía')).toBeTruthy();
    await fireEvent.press(screen.getByRole('button', { name: 'Buscar productos' }));
    expect(await screen.findByLabelText('Buscar productos')).toBeTruthy();
  });
});

describe('search', () => {
  const server = () =>
    fakeApi({
      'GET /api/v1/pantry': page([]),
      'GET /api/v1/products': ({ query }: { query: Record<string, string> }) =>
        query.q === 'zzz' ? page([]) : page([product()]),
    });

  it('searches while typing and shows price and unit price', async () => {
    const api = server();
    await renderConnected(<ProductsScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('radio', { name: 'Buscar' }));
    await fireEvent.changeText(screen.getByLabelText('Buscar productos'), 'arroz');
    expect(await screen.findByText('Arroz redondo Hacendado')).toBeTruthy();
    expect(screen.getByText(/mercadona · 1,15 € · 1,15 €\/kg/)).toBeTruthy();
    expect(api.called('GET /api/v1/products')[0].query.q).toBe('arroz');
    await fireEvent.press(screen.getByRole('button', { name: /Arroz redondo Hacendado/ }));
    expect(router.push).toHaveBeenCalledWith('/products/5');
  });

  it('does not search for one letter and reports no results', async () => {
    const api = server();
    await renderConnected(<ProductsScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('radio', { name: 'Buscar' }));
    await fireEvent.changeText(screen.getByLabelText('Buscar productos'), 'a');
    expect(await screen.findByText('Escribe al menos dos letras.')).toBeTruthy();
    expect(api.called('GET /api/v1/products')).toHaveLength(0);
    await fireEvent.changeText(screen.getByLabelText('Buscar productos'), 'zzz');
    expect(await screen.findByText('No hay resultados')).toBeTruthy();
  });
});

describe('product detail', () => {
  beforeEach(() => params.mockReturnValue({ id: '5' }));
  const routes = (extra: Record<string, unknown> = {}, p = product()) => ({
    'GET /api/v1/products/5': p,
    'GET /api/v1/pantry': page([]),
    ...extra,
  });

  it('shows price, package and where the nutrition comes from', async () => {
    await renderConnected(<ProductScreen />, fakeApi(routes()).fetchImpl);
    expect(await screen.findByText('Arroz redondo Hacendado')).toBeTruthy();
    expect(screen.getByText(/Envase: 1 kg/)).toBeTruthy();
    expect(screen.getByText('Nutrición por 100 g')).toBeTruthy();
    expect(screen.getByText('344 kcal')).toBeTruthy();
    expect(screen.getByText('Fuente: Open Food Facts.')).toBeTruthy();
  });

  it('warns that generic reference nutrition is approximate', async () => {
    const generic = product({ nutrition: { basis: 'g', energy_kcal: '365', protein_g: '7.13', fat_g: '0.66', carbohydrates_g: '79.95', source: 'sample' } as never });
    await renderConnected(<ProductScreen />, fakeApi(routes({}, generic)).fetchImpl);
    expect(await screen.findByText(/Valores aproximados \(alimento genérico de referencia\)/)).toBeTruthy();
  });

  /** A server that remembers what was saved, like the real one. */
  function statefulProduct() {
    let current = product();
    return fakeApi(
      routes({
        'GET /api/v1/products/5': () => current,
        'PATCH /api/v1/products/5': ({ body }: { body: { allergens: never[] } }) => {
          current = product({ allergens: body.allergens, allergens_source: 'manual' });
          return current;
        },
      }),
    );
  }

  it('warns about unknown allergens and lets the person set them by hand', async () => {
    const api = statefulProduct();
    await renderConnected(<ProductScreen />, api.fetchImpl);
    expect(await screen.findByText('Alérgenos desconocidos')).toBeTruthy();
    expect(screen.getByText(/no se te propondrá hasta que lo indiques tú/)).toBeTruthy();

    await fireEvent.press(screen.getByRole('button', { name: 'Indicar alérgenos' }));
    await fireEvent.press(screen.getByRole('checkbox', { name: 'Leche' }));
    await fireEvent.press(screen.getByRole('checkbox', { name: 'Gluten' }));
    await fireEvent.press(screen.getByRole('button', { name: 'Guardar alérgenos' }));
    await screen.findByText('Gluten, Leche');
    expect(screen.queryByText('Alérgenos desconocidos')).toBeNull();
    expect(screen.getByText('Fuente: indicado por ti.')).toBeTruthy();
    expect(api.called('PATCH /api/v1/products/5')[0].body).toMatchObject({ allergens: ['gluten', 'milk'] });
  });

  it('can state that a product contains none of the 14 allergens', async () => {
    const api = statefulProduct();
    await renderConnected(<ProductScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Indicar alérgenos' }));
    await fireEvent(screen.getByLabelText('No contiene ninguno'), 'valueChange', true);
    await fireEvent.press(screen.getByRole('button', { name: 'Guardar alérgenos' }));
    expect(await screen.findByText(/No contiene ninguno de los 14/)).toBeTruthy();
    expect(api.called('PATCH /api/v1/products/5')[0].body).toMatchObject({ allergens: [] });
  });

  it('adds to the pantry with a validated amount', async () => {
    const api = fakeApi(routes({ 'POST /api/v1/pantry': pantryItem(9, 5, 'Arroz', 'grains', '500') }));
    await renderConnected(<ProductScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Añadir a la despensa' }));
    expect(await screen.findByText('Escribe una cantidad válida.')).toBeTruthy();
    expect(api.called('POST /api/v1/pantry')).toHaveLength(0);
    await fireEvent.changeText(screen.getByLabelText('Cantidad'), '500,5');
    await fireEvent.press(screen.getByRole('button', { name: 'Añadir a la despensa' }));
    await screen.findByRole('button', { name: 'Añadir a la despensa' });
    expect(api.called('POST /api/v1/pantry')[0].body).toEqual({ product_id: 5, amount: '500.5', unit: 'g', expires_at: null });
  });

  it('updates or removes an item already in the pantry', async () => {
    const item = pantryItem(9, 5, 'Arroz', 'grains', '500');
    const api = fakeApi(
      routes({
        'GET /api/v1/pantry': page([item]),
        'PUT /api/v1/pantry/9': { ...item, amount: '300' },
        'DELETE /api/v1/pantry/9': () => undefined,
      }),
    );
    await renderConnected(<ProductScreen />, api.fetchImpl);
    expect(await screen.findByDisplayValue('500')).toBeTruthy();
    await fireEvent.changeText(screen.getByLabelText('Cantidad'), '300');
    await fireEvent.press(screen.getByRole('button', { name: 'Guardar cantidad' }));
    await screen.findByDisplayValue('300');
    expect(api.called('PUT /api/v1/pantry/9')[0].body).toMatchObject({ product_id: 5, amount: '300' });
    await fireEvent.press(screen.getByRole('button', { name: 'Quitar de la despensa' }));
    await screen.findByRole('button', { name: 'Añadir a la despensa' }).catch(() => null);
    expect(api.called('DELETE /api/v1/pantry/9')).toHaveLength(1);
  });
});
