// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, screen, waitFor } from '@testing-library/react-native';
import { useLocalSearchParams } from 'expo-router';

import RecipeScreen from '@/app/(app)/recipe';
import { apiError, fakeApi } from '../test-utils/fakeApi';
import { cookOut, recipeOut } from '../test-utils/fixtures';
import { renderConnected } from '../test-utils/render';
import { resetRouter } from '../test-utils/router';

const params = useLocalSearchParams as jest.Mock;
const RECIPE = 'POST /api/v1/meals/recipe';

beforeEach(() => {
  resetRouter();
  params.mockReturnValue({ day: '2026-11-26', slot: 'lunch' });
});

describe('recipe', () => {
  it('shows ingredients, steps with heat, dial level and times, and the total', async () => {
    const api = fakeApi({ [RECIPE]: recipeOut() });
    await renderConnected(<RecipeScreen />, api.fetchImpl);
    expect(await screen.findByText('Arroz con pollo')).toBeTruthy();
    expect(screen.getByText('Para Pablo')).toBeTruthy();
    expect(screen.getByText('Pechuga de pollo: 300 g')).toBeTruthy();
    expect(screen.getByText('1. Corta pechuga de pollo (300 g) en dados.')).toBeTruthy();
    expect(screen.getByText('~5 min')).toBeTruthy(); // no appliance: only the estimated time
    expect(screen.getByText('placa · fuego alto · nivel 7 (aprox.) · 11 min')).toBeTruthy(); // calibrated boil
    expect(screen.getByText('placa · fuego medio · nivel 5 (aprox.) · ~10 min')).toBeTruthy();
    expect(screen.getByText('Tiempo total aproximado: 26 min')).toBeTruthy();
    expect(api.called(RECIPE)[0].body).toEqual({ day: '2026-11-26', slot: 'lunch', regenerate: false });
  });

  it('suggests calibrating the hob only when it is not calibrated', async () => {
    await renderConnected(<RecipeScreen />, fakeApi({ [RECIPE]: recipeOut() }).fetchImpl);
    expect(await screen.findByText(/Mide tu placa en Herramientas/)).toBeTruthy();
  });

  it('does not mention calibration when the hob is calibrated', async () => {
    await renderConnected(<RecipeScreen />, fakeApi({ [RECIPE]: recipeOut({ calibrated: true }) }).fetchImpl);
    await screen.findByText('Arroz con pollo');
    expect(screen.queryByText(/Mide tu placa/)).toBeNull();
  });

  it('tells the person the AI is writing the recipe while it waits', async () => {
    let release: (value: unknown) => void = () => {};
    const slow = new Promise((resolve) => (release = resolve));
    const api = fakeApi({ [RECIPE]: async () => (await slow, recipeOut()) });
    await renderConnected(<RecipeScreen />, api.fetchImpl);
    expect(await screen.findByText('Escribiendo la receta…')).toBeTruthy();
    release(null);
    expect(await screen.findByText('Arroz con pollo')).toBeTruthy();
  });

  it('explains a recipe the checks rejected, and lets the person try again', async () => {
    let attempts = 0;
    const api = fakeApi({
      [RECIPE]: () => (++attempts === 1 ? apiError(422, 'recipe_rejected', 'the AI recipe did not pass', ['oven']) : recipeOut()),
    });
    await renderConnected(<RecipeScreen />, api.fetchImpl);
    expect(await screen.findByText('La receta no ha pasado las comprobaciones')).toBeTruthy();
    await fireEvent.press(screen.getByRole('button', { name: 'Intentar de nuevo' }));
    expect(await screen.findByText('Arroz con pollo')).toBeTruthy();
  });

  it('says so when the meal is not in the menu', async () => {
    const api = fakeApi({ [RECIPE]: apiError(404, 'not_found', 'no lunch planned') });
    await renderConnected(<RecipeScreen />, api.fetchImpl);
    expect(await screen.findByText('Esta comida no está en tu menú.')).toBeTruthy();
  });

  it('asks the server for another recipe', async () => {
    const api = fakeApi({
      [RECIPE]: ({ body }: { body: { regenerate: boolean } }) =>
        body.regenerate ? recipeOut({ title: 'Arroz con pollo (otra)' }) : recipeOut(),
    });
    await renderConnected(<RecipeScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Otra receta' }));
    expect(await screen.findByText('Arroz con pollo (otra)')).toBeTruthy();
    expect(api.called(RECIPE).at(-1)?.body).toMatchObject({ regenerate: true });
  });
});

describe('marking as cooked', () => {
  const preview = cookOut([
    { product_id: 1, name: 'Arroz', needed: '200', in_pantry: '500', deduct: '200' },
    { product_id: 2, name: 'Pechuga de pollo', needed: '300', in_pantry: '120', deduct: '120', note: 'not_enough' },
    { product_id: 3, name: 'Cebolla', needed: '100', in_pantry: '0', deduct: '0', missing: '100', note: 'not_in_pantry' },
  ]);

  it('shows what would change, lets the person skip a product, and only then applies it', async () => {
    const api = fakeApi({
      [RECIPE]: recipeOut(),
      'GET /api/v1/meals/cook-preview': preview,
      'POST /api/v1/meals/cook': cookOut([]),
    });
    await renderConnected(<RecipeScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Marcar como cocinado' }));
    expect(await screen.findByText('Arroz: se descuenta 200 g de 200 g')).toBeTruthy();
    expect(screen.getByText('Solo tienes 120 g: se descuenta eso.')).toBeTruthy();
    expect(screen.getByText('No está en tu despensa: no se descuenta nada.')).toBeTruthy();
    expect(api.called('POST /api/v1/meals/cook')).toHaveLength(0); // nothing applied yet

    await fireEvent(screen.getByLabelText('No descontar Arroz'), 'valueChange', true);
    await fireEvent.press(screen.getByRole('button', { name: 'Confirmar y marcar como cocinado' }));
    expect(await screen.findByText('Hecho: despensa actualizada.')).toBeTruthy();
    expect(api.called('POST /api/v1/meals/cook')[0].body).toEqual({ day: '2026-11-26', slot: 'lunch', skip_products: [1] });
  });

  it('can be cancelled without touching the pantry', async () => {
    const api = fakeApi({ [RECIPE]: recipeOut(), 'GET /api/v1/meals/cook-preview': preview });
    await renderConnected(<RecipeScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Marcar como cocinado' }));
    await fireEvent.press(await screen.findByRole('button', { name: 'Cancelar' }));
    expect(screen.getByRole('button', { name: 'Marcar como cocinado' })).toBeTruthy();
    expect(api.called('POST /api/v1/meals/cook')).toHaveLength(0);
  });

  it('says when nothing can be deducted because the pantry is empty', async () => {
    const empty = cookOut([{ name: 'Arroz', in_pantry: '0', deduct: '0', missing: '200', note: 'not_in_pantry' }]);
    const api = fakeApi({ [RECIPE]: recipeOut(), 'GET /api/v1/meals/cook-preview': empty });
    await renderConnected(<RecipeScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Marcar como cocinado' }));
    expect(await screen.findByText(/No hay nada que descontar/)).toBeTruthy();
  });

  it('shows an already cooked meal as such and does not offer it again', async () => {
    const api = fakeApi({ [RECIPE]: recipeOut({ cooked_at: '2026-11-26T13:30:00Z' }) });
    await renderConnected(<RecipeScreen />, api.fetchImpl);
    expect(await screen.findByText('Esta comida ya estaba marcada como cocinada.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Marcar como cocinado' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Otra receta' }).props.accessibilityState.disabled).toBe(true);
  });

  it('reports a failure to apply and keeps the confirmation open', async () => {
    const api = fakeApi({
      [RECIPE]: recipeOut(),
      'GET /api/v1/meals/cook-preview': preview,
      'POST /api/v1/meals/cook': apiError(409, 'already_cooked', 'already marked'),
    });
    await renderConnected(<RecipeScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Marcar como cocinado' }));
    await fireEvent.press(await screen.findByRole('button', { name: 'Confirmar y marcar como cocinado' }));
    await waitFor(() => expect(api.called('POST /api/v1/meals/cook')).toHaveLength(1));
    expect(await screen.findByText('already marked')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Confirmar y marcar como cocinado' })).toBeTruthy();
  });
});
