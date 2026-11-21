// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, screen } from '@testing-library/react-native';
import { useLocalSearchParams } from 'expo-router';

import CreateMenuScreen from '@/app/(app)/menu/create';
import MenuScreen from '@/app/(app)/menu/index';
import { addDays, localISODate, mondayOf } from '@/i18n';
import { apiError, fakeApi } from '../test-utils/fakeApi';
import { meal, plan, profile } from '../test-utils/fixtures';
import { renderConnected } from '../test-utils/render';
import { resetRouter, router } from '../test-utils/router';

const params = useLocalSearchParams as jest.Mock;
const WEEK = '2026-11-23';

beforeEach(() => {
  resetRouter();
  params.mockReturnValue({});
});

describe('weekly menu', () => {
  const thisWeek = mondayOf(localISODate());
  const meals = [
    meal('lunch', 'Pasta con garbanzos', thisWeek),
    meal('breakfast', 'Gachas de avena', thisWeek),
    meal('dinner', 'Sopa de pasta', addDays(thisWeek, 1)),
  ];

  it('lists the days with their meals in order, and expands a meal', async () => {
    const server = fakeApi({ 'GET /api/v1/profiles': [profile()], 'GET /api/v1/plans': plan(thisWeek, meals) });
    await renderConnected(<MenuScreen />, server.fetchImpl);
    const first = await screen.findByRole('button', { name: 'Desayuno: Gachas de avena' });
    expect(first).toBeTruthy();
    expect(screen.getAllByRole('header').length).toBe(2); // two days
    await fireEvent.press(screen.getByRole('button', { name: 'Comida: Pasta con garbanzos' }));
    expect(await screen.findByText('Arroz 100 g · Aceite 1,5 l')).toBeTruthy();
    expect(server.called('GET /api/v1/plans')[0].query.week).toBe(thisWeek);
  });

  it('moves between weeks', async () => {
    const server = fakeApi({ 'GET /api/v1/profiles': [profile()], 'GET /api/v1/plans': null });
    await renderConnected(<MenuScreen />, server.fetchImpl);
    await screen.findByText('No hay menú para esta semana');
    await fireEvent.press(screen.getByRole('button', { name: 'Semana siguiente' }));
    await screen.findByText('No hay menú para esta semana');
    expect(server.called('GET /api/v1/plans').map((c) => c.query.week)).toEqual([thisWeek, addDays(thisWeek, 7)]);
  });

  it('offers to create the menu of the shown week', async () => {
    const server = fakeApi({ 'GET /api/v1/profiles': [profile()], 'GET /api/v1/plans': null });
    await renderConnected(<MenuScreen />, server.fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Crear menú de esta semana' }));
    expect(router.push).toHaveBeenCalledWith({ pathname: '/menu/create', params: { week: thisWeek } });
  });
});

describe('create menu', () => {
  const stores = [{ store_id: 'mercadona', products: 25, priced: 25 }];
  const accepted = { job_id: 'j1', status_url: '/api/v1/jobs/j1' };
  const job = (status: string, result: unknown = null, error: string | null = null) => ({ id: 'j1', kind: 'plan_week', status, result, error });

  function server(extra: Record<string, unknown>) {
    return fakeApi({ 'GET /api/v1/catalog/stores': stores, 'POST /api/v1/plans': accepted, ...extra });
  }

  beforeEach(() => params.mockReturnValue({ week: WEEK }));

  it('says what is missing when no store has products', async () => {
    await renderConnected(<CreateMenuScreen />, fakeApi({ 'GET /api/v1/catalog/stores': [] }).fetchImpl);
    expect(await screen.findByText('Aún no hay productos de ninguna tienda')).toBeTruthy();
  });

  it('sends the whole week by default and shows progress while generating', async () => {
    const api = server({ 'GET /api/v1/jobs/j1': job('running') });
    await renderConnected(<CreateMenuScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Generar menú' }));
    expect(await screen.findByText('Generando el menú…')).toBeTruthy();
    expect(screen.getByText(/30 y 90 segundos/)).toBeTruthy();
    expect(api.called('POST /api/v1/plans')[0].body).toMatchObject({
      store_id: 'mercadona', variety: 'basic', regenerate: false,
      schedule: { week_start: WEEK, weekdays: [0, 1, 2, 3, 4, 5, 6], skip: [] },
    });
  });

  it('sends the meals the person unticked as skipped', async () => {
    const api = server({ 'GET /api/v1/jobs/j1': job('running') });
    await renderConnected(<CreateMenuScreen />, api.fetchImpl);
    await screen.findByRole('button', { name: 'Generar menú' });
    for (const day of ['martes, 24 nov', 'jueves, 26 nov']) {
      await fireEvent(screen.getByLabelText(`${day}, Cena`), 'valueChange', false);
    }
    await fireEvent(screen.getByLabelText('sábado, 28 nov, Desayuno'), 'valueChange', false);
    await fireEvent.press(screen.getByRole('radio', { name: 'Equilibrada' }));
    await fireEvent.press(screen.getByRole('button', { name: 'Generar menú' }));
    await screen.findByText('Generando el menú…');
    const body = api.called('POST /api/v1/plans')[0].body as { schedule: { skip: unknown[] }; variety: string };
    expect(body.variety).toBe('balanced');
    expect(body.schedule.skip).toEqual([[1, 'dinner'], [3, 'dinner'], [5, 'breakfast']]);
  });

  it('cannot generate an empty plan', async () => {
    await renderConnected(<CreateMenuScreen />, server({}).fetchImpl);
    await screen.findByRole('button', { name: 'Generar menú' });
    for (const slot of ['Desayuno', 'Comida', 'Merienda', 'Cena']) {
      for (const day of ['lunes, 23 nov', 'martes, 24 nov', 'miércoles, 25 nov', 'jueves, 26 nov', 'viernes, 27 nov', 'sábado, 28 nov', 'domingo, 29 nov']) {
        await fireEvent(screen.getByLabelText(`${day}, ${slot}`), 'valueChange', false);
      }
    }
    expect(screen.getByRole('button', { name: 'Generar menú' }).props.accessibilityState.disabled).toBe(true);
  });

  it('asks before replacing an existing plan', async () => {
    let calls = 0;
    const api = server({
      'POST /api/v1/plans': () => (++calls === 1 ? apiError(409, 'plan_exists', 'already') : accepted),
      'GET /api/v1/jobs/j1': job('running'),
    });
    await renderConnected(<CreateMenuScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Generar menú' }));
    expect(await screen.findByText('Ya hay un menú para esta semana')).toBeTruthy();
    await fireEvent.press(screen.getByRole('button', { name: 'Reemplazarlo' }));
    await screen.findByText('Generando el menú…');
    expect(api.called('POST /api/v1/plans').map((c) => (c.body as { regenerate: boolean }).regenerate)).toEqual([false, true]);
  });

  it('shows the finished menu, the extra packs and goes to the menu', async () => {
    const api = server({
      'GET /api/v1/jobs/j1': job('done', { accepted: true, shopping_status: 'optimal', extra_purchases: [{ name: 'Garbanzos', packs: 1 }] }),
    });
    await renderConnected(<CreateMenuScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Generar menú' }));
    expect(await screen.findByText('Menú creado')).toBeTruthy();
    expect(screen.getByText(/paquetes extra.*1 × Garbanzos/)).toBeTruthy();
    await fireEvent.press(screen.getByRole('button', { name: 'Ver menú' }));
    expect(router.replace).toHaveBeenCalledWith({ pathname: '/menu', params: { week: WEEK } });
  });

  it('explains an impossible shop in money', async () => {
    const api = server({
      'GET /api/v1/jobs/j1': job('done', {
        shopping_status: 'infeasible',
        shortfalls: [{ constraint: 'budget', amount: '740', unit: 'cents', detail: 'needs more money' }],
      }),
    });
    await renderConnected(<CreateMenuScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Generar menú' }));
    expect(await screen.findByText('Con estos datos no hay una compra posible')).toBeTruthy();
    expect(screen.getByText(/Faltan 7,40 € de presupuesto/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Intentar de nuevo' })).toBeTruthy();
  });

  it('lists the problems of a menu that failed the checks', async () => {
    const api = server({
      'GET /api/v1/jobs/j1': job('done', { shopping_status: 'optimal', accepted: false, issues: ['Pablo wants fish at least 2 times'] }),
    });
    await renderConnected(<CreateMenuScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Generar menú' }));
    expect(await screen.findByText('El menú no ha pasado las comprobaciones')).toBeTruthy();
    expect(screen.getByText(/Pablo wants fish/)).toBeTruthy();
  });

  it('reports a failed job and lets the person try again', async () => {
    const api = server({ 'GET /api/v1/jobs/j1': job('failed', null, "LLMOutputError('bad')") });
    await renderConnected(<CreateMenuScreen />, api.fetchImpl);
    await fireEvent.press(await screen.findByRole('button', { name: 'Generar menú' }));
    expect(await screen.findByText('No se pudo generar el menú')).toBeTruthy();
    await fireEvent.press(screen.getByRole('button', { name: 'Intentar de nuevo' }));
    expect(await screen.findByRole('button', { name: 'Generar menú' })).toBeTruthy();
  });
});
