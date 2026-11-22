// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, screen, waitFor } from '@testing-library/react-native';
import { useLocalSearchParams } from 'expo-router';

import ProfileScreen from '@/app/(app)/settings/profile/[id]';
import SettingsScreen from '@/app/(app)/settings/index';
import ShoppingScreen from '@/app/(app)/shopping';
import ToolsScreen from '@/app/(app)/tools';
import * as confirm from '@/components/confirm';
import { apiError, fakeApi } from '../test-utils/fakeApi';
import { household, plan, profile } from '../test-utils/fixtures';
import { renderConnected } from '../test-utils/render';
import { resetRouter, router } from '../test-utils/router';

const params = useLocalSearchParams as jest.Mock;
const equipment = {
  id: 1, household_id: 1, hob_type: 'induction', burners: 3, oven: false, microwave: true,
  air_fryer: false, power_levels: null, calibration_level: null, calibration_boil_1l_minutes: null,
};

beforeEach(() => {
  resetRouter();
  jest.restoreAllMocks();
});

describe('tools', () => {
  it('shows the saved kitchen and saves changes', async () => {
    const api = fakeApi({ 'GET /api/v1/equipment': equipment, 'PUT /api/v1/equipment': equipment });
    await renderConnected(<ToolsScreen />, api.fetchImpl);
    expect(await screen.findByText('Sin horno, el menú no incluirá platos al horno.')).toBeTruthy();
    expect(screen.getByRole('radio', { name: 'Inducción', selected: true })).toBeTruthy();
    await fireEvent(screen.getByLabelText('Horno'), 'valueChange', true);
    await fireEvent.press(screen.getByRole('button', { name: 'Más' }));
    await fireEvent.press(screen.getByRole('button', { name: 'Guardar' }));
    await waitFor(() => expect(api.called('PUT /api/v1/equipment')).toHaveLength(1));
    expect(api.called('PUT /api/v1/equipment')[0].body).toMatchObject({
      hob_type: 'induction', burners: 4, oven: true, microwave: true, air_fryer: false,
    });
    expect(await screen.findByText('Guardado')).toBeTruthy();
  });

  it('starts from defaults when no kitchen was saved yet', async () => {
    await renderConnected(<ToolsScreen />, fakeApi({ 'GET /api/v1/equipment': null }).fetchImpl);
    expect(await screen.findByText('Calibración de la placa')).toBeTruthy();
    expect(screen.getByRole('radio', { name: 'Inducción', selected: true })).toBeTruthy();
  });
});

describe('shopping list', () => {
  const list = (checked = false) => ({
    store_id: 'mercadona', total_cents: 1250,
    items: [{ id: 3, product_id: 5, name: 'Arroz', packs: 2, unit_price_cents: 115, checked }],
  });

  it('lists the items and ticks one', async () => {
    let checked = false;
    const api = fakeApi({
      'GET /api/v1/plans': plan('2026-11-16', []),
      'GET /api/v1/plans/7/shopping-list': () => list(checked),
      'PATCH /api/v1/shopping-items/3': ({ body }: { body: { checked: boolean } }) => {
        checked = body.checked;
        return { ...list(checked).items[0] };
      },
    });
    await renderConnected(<ShoppingScreen />, api.fetchImpl);
    expect(await screen.findByText('Tienda: mercadona')).toBeTruthy();
    expect(screen.getByText('Total: 12,50 €')).toBeTruthy();
    expect(screen.getByText('0 de 1 marcados')).toBeTruthy();
    await fireEvent.press(screen.getByRole('checkbox', { name: '2 × Arroz' }));
    expect(await screen.findByText('1 de 1 marcados')).toBeTruthy();
    expect(api.called('PATCH /api/v1/shopping-items/3')[0].body).toEqual({ checked: true });
  });

  it('explains when there is no plan this week', async () => {
    await renderConnected(<ShoppingScreen />, fakeApi({ 'GET /api/v1/plans': null }).fetchImpl);
    expect(await screen.findByText('No hay lista de la compra')).toBeTruthy();
  });
});

describe('settings', () => {
  const llm = {
    thinking: false, spent_usd: '0.12',
    models: [
      { tier: 'small', model: 'deepseek/deepseek-flash', provider: 'deepseek', key_configured: true },
      { tier: 'large', model: 'deepseek/deepseek-v4-pro', provider: 'deepseek', key_configured: false },
    ],
  };

  it('shows the household, people and AI status without any key', async () => {
    await renderConnected(
      <SettingsScreen />,
      fakeApi({ 'GET /api/v1/household': household, 'GET /api/v1/profiles': [profile()], 'GET /api/v1/settings/llm': llm }).fetchImpl,
    );
    expect(await screen.findByDisplayValue('Casa')).toBeTruthy();
    expect(screen.getByDisplayValue('60')).toBeTruthy();
    expect(await screen.findByText('deepseek/deepseek-flash')).toBeTruthy();
    expect(screen.getByText('clave configurada en el servidor')).toBeTruthy();
    expect(screen.getByText('falta la clave en el servidor')).toBeTruthy();
    expect(screen.getByText('Gasto de IA registrado: 0.12 $')).toBeTruthy();
    await fireEvent.press(screen.getByRole('button', { name: 'Pablo' }));
    expect(router.push).toHaveBeenCalledWith('/settings/profile/1');
    await fireEvent.press(screen.getByRole('button', { name: 'Añadir persona' }));
    expect(router.push).toHaveBeenCalledWith('/settings/profile/new');
  });

  it('creates the household on first run and rejects a bad amount', async () => {
    const api = fakeApi({
      'GET /api/v1/household': apiError(409, 'setup_required', 'create the household first'),
      'GET /api/v1/settings/llm': llm,
      'PUT /api/v1/household': household,
    });
    await renderConnected(<SettingsScreen />, api.fetchImpl);
    expect(await screen.findByText(/Empieza creando tu hogar/)).toBeTruthy();
    await fireEvent.changeText(screen.getByLabelText('Nombre del hogar'), 'Casa');
    await fireEvent.changeText(screen.getByLabelText('Presupuesto semanal (€)'), 'mucho');
    await fireEvent.press(screen.getByRole('button', { name: 'Crear hogar' }));
    expect(await screen.findByText(/Escribe un importe válido/)).toBeTruthy();
    expect(api.called('PUT /api/v1/household')).toHaveLength(0);
    await fireEvent.changeText(screen.getByLabelText('Presupuesto semanal (€)'), '59,90');
    await fireEvent.press(screen.getByRole('button', { name: 'Crear hogar' }));
    await waitFor(() => expect(api.called('PUT /api/v1/household')).toHaveLength(1));
    expect(api.called('PUT /api/v1/household')[0].body).toEqual({ name: 'Casa', weekly_budget_cents: 5990, currency: 'EUR' });
  });
});

describe('profile editor', () => {
  it('validates, then creates a person', async () => {
    params.mockReturnValue({ id: 'new' });
    const api = fakeApi({ 'POST /api/v1/profiles': profile('Ana', 2) });
    await renderConnected(<ProfileScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Guardar persona' }));
    expect(await screen.findByText('Escribe un nombre.')).toBeTruthy();
    expect(screen.getByText('Usa el formato AAAA-MM-DD.')).toBeTruthy();
    expect(api.called('POST /api/v1/profiles')).toHaveLength(0);

    await fireEvent.changeText(screen.getByLabelText('Nombre'), 'Ana');
    await fireEvent.changeText(screen.getByLabelText('Fecha de nacimiento (AAAA-MM-DD)'), '1990-05-01');
    await fireEvent.changeText(screen.getByLabelText('Altura (cm)'), '165');
    await fireEvent.changeText(screen.getByLabelText('Peso (kg)'), '60,5');
    await fireEvent.press(screen.getByRole('checkbox', { name: 'Gluten' }));
    await fireEvent.changeText(screen.getByLabelText('Carne'), '3');
    await fireEvent.changeText(screen.getByLabelText('Tipo de alimento'), 'Carrot');
    await fireEvent.press(screen.getByRole('button', { name: 'Añadir' }));
    await fireEvent.press(screen.getByRole('button', { name: 'Guardar persona' }));
    await waitFor(() => expect(api.called('POST /api/v1/profiles')).toHaveLength(1));
    expect(api.called('POST /api/v1/profiles')[0].body).toMatchObject({
      name: 'Ana', sex: 'female', birth_date: '1990-05-01', height_cm: 165, weight_kg: 60.5,
      allergies: ['gluten'], weekly_servings: { meat: 3 }, food_preferences: { carrot: 'less' },
    });
    await waitFor(() => expect(router.back).toHaveBeenCalled());
  });

  it('saves an own protein target, or none when left empty', async () => {
    params.mockReturnValue({ id: 'new' });
    const api = fakeApi({ 'POST /api/v1/profiles': profile('Ana', 2) });
    await renderConnected(<ProfileScreen />, api.fetchImpl);
    await fireEvent.changeText(await screen.findByLabelText('Nombre'), 'Ana');
    await fireEvent.changeText(screen.getByLabelText('Fecha de nacimiento (AAAA-MM-DD)'), '1990-05-01');
    await fireEvent.changeText(screen.getByLabelText('Altura (cm)'), '165');
    await fireEvent.changeText(screen.getByLabelText('Peso (kg)'), '60');
    await fireEvent.changeText(screen.getByLabelText('Proteína (g por kg de peso al día)'), '5');
    await fireEvent.press(screen.getByRole('button', { name: 'Guardar persona' }));
    expect(await screen.findByText('Escribe un valor entre 0,8 y 3, o déjalo vacío.')).toBeTruthy();
    expect(api.called('POST /api/v1/profiles')).toHaveLength(0);
    await fireEvent.changeText(screen.getByLabelText('Proteína (g por kg de peso al día)'), '1,6');
    await fireEvent.press(screen.getByRole('button', { name: 'Guardar persona' }));
    await waitFor(() => expect(api.called('POST /api/v1/profiles')).toHaveLength(1));
    expect(api.called('POST /api/v1/profiles')[0].body).toMatchObject({ protein_g_per_kg: 1.6 });
  });

  it('sends null when the protein field is empty', async () => {
    params.mockReturnValue({ id: 'new' });
    const api = fakeApi({ 'POST /api/v1/profiles': profile('Ana', 2) });
    await renderConnected(<ProfileScreen />, api.fetchImpl);
    await fireEvent.changeText(await screen.findByLabelText('Nombre'), 'Ana');
    await fireEvent.changeText(screen.getByLabelText('Fecha de nacimiento (AAAA-MM-DD)'), '1990-05-01');
    await fireEvent.changeText(screen.getByLabelText('Altura (cm)'), '165');
    await fireEvent.changeText(screen.getByLabelText('Peso (kg)'), '60');
    await fireEvent.press(screen.getByRole('button', { name: 'Guardar persona' }));
    await waitFor(() => expect(api.called('POST /api/v1/profiles')).toHaveLength(1));
    expect(api.called('POST /api/v1/profiles')[0].body).toMatchObject({ protein_g_per_kg: null });
  });

  it('shows the server field errors', async () => {
    params.mockReturnValue({ id: 'new' });
    const api = fakeApi({
      'POST /api/v1/profiles': apiError(422, 'validation_error', 'invalid', [{ field: 'allergies_confirmed', message: 'confirm your allergies' }]),
    });
    await renderConnected(<ProfileScreen />, api.fetchImpl);
    await fireEvent.changeText(await screen.findByLabelText('Nombre'), 'Ana');
    await fireEvent.changeText(screen.getByLabelText('Fecha de nacimiento (AAAA-MM-DD)'), '1990-05-01');
    await fireEvent.changeText(screen.getByLabelText('Altura (cm)'), '165');
    await fireEvent.changeText(screen.getByLabelText('Peso (kg)'), '60');
    await fireEvent.press(screen.getByRole('button', { name: 'Guardar persona' }));
    expect(await screen.findByText('confirm your allergies')).toBeTruthy();
    expect(router.back).not.toHaveBeenCalled();
  });

  it('edits an existing person and deletes after confirming', async () => {
    params.mockReturnValue({ id: '1' });
    const api = fakeApi({
      'GET /api/v1/profiles': [profile('Pablo', 1)],
      'DELETE /api/v1/profiles/1': () => undefined,
    });
    const ask = jest.spyOn(confirm, 'confirmAction').mockResolvedValue(true);
    await renderConnected(<ProfileScreen />, api.fetchImpl);
    expect(await screen.findByDisplayValue('Pablo')).toBeTruthy();
    expect(screen.getByDisplayValue('185')).toBeTruthy();
    expect(screen.getByText(/3336 kcal/)).toBeTruthy();
    await fireEvent.press(screen.getByRole('button', { name: 'Eliminar persona' }));
    await waitFor(() => expect(api.called('DELETE /api/v1/profiles/1')).toHaveLength(1));
    expect(ask).toHaveBeenCalled();
    await waitFor(() => expect(router.back).toHaveBeenCalled());
  });

  it('does not delete when the person cancels', async () => {
    params.mockReturnValue({ id: '1' });
    const api = fakeApi({ 'GET /api/v1/profiles': [profile('Pablo', 1)] });
    jest.spyOn(confirm, 'confirmAction').mockResolvedValue(false);
    await renderConnected(<ProfileScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Eliminar persona' }));
    expect(api.called('DELETE /api/v1/profiles/1')).toHaveLength(0);
  });
});
