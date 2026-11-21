// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, screen } from '@testing-library/react-native';

import { localISODate, mondayOf } from '@/i18n';
import TodayScreen from '@/app/(app)/index';
import { apiError, fakeApi } from '../test-utils/fakeApi';
import { meal, plan, profile } from '../test-utils/fixtures';
import { renderConnected } from '../test-utils/render';
import { resetRouter, router } from '../test-utils/router';

const NO_TIMERS = ['nextTick', 'setImmediate', 'clearImmediate', 'setInterval', 'clearInterval', 'setTimeout', 'clearTimeout', 'queueMicrotask', 'requestAnimationFrame', 'cancelAnimationFrame', 'requestIdleCallback', 'cancelIdleCallback', 'hrtime', 'performance'] as const;

beforeEach(() => {
  resetRouter();
  // Only the clock: it is 13:00, lunch time.
  jest.useFakeTimers({ now: new Date(2026, 10, 26, 13, 0), doNotFake: [...NO_TIMERS] });
});
afterEach(() => jest.useRealTimers());

const today = () => localISODate();
const meals = [meal('breakfast', 'Gachas de avena'), meal('lunch', 'Pasta con garbanzos', today(), { needs: ['air_fryer'] }), meal('dinner', 'Sopa de pasta')];

it("shows today's recipe with the member's portions, and the other meals collapsed", async () => {
  const server = fakeApi({
    'GET /api/v1/profiles': [profile()],
    'GET /api/v1/today': meals,
    'GET /api/v1/plans': plan(mondayOf(today()), meals),
  });
  await renderConnected(<TodayScreen />, server.fetchImpl);

  expect(await screen.findByText('Receta del día')).toBeTruthy();
  expect(screen.getByText('Pasta con garbanzos')).toBeTruthy(); // lunch at 13:00
  expect(screen.getByText('Comida · airfryer')).toBeTruthy();
  expect(screen.getByText('Arroz 100 g · Aceite 1,5 l')).toBeTruthy(); // formatted amounts
  expect(screen.getByText('Prepara pasta con garbanzos.')).toBeTruthy();
  expect(screen.queryByText('Prepara gachas de avena.')).toBeNull(); // others collapsed

  await fireEvent.press(screen.getByRole('button', { name: /Desayuno: Gachas de avena/ }));
  expect(await screen.findByText('Prepara gachas de avena.')).toBeTruthy();
  expect(server.called('GET /api/v1/today')[0].query).toMatchObject({ day: today(), profile_id: '1' });
});

it('scan and chat are visible but disabled until their phases', async () => {
  const server = fakeApi({ 'GET /api/v1/profiles': [profile()], 'GET /api/v1/today': meals, 'GET /api/v1/plans': null });
  await renderConnected(<TodayScreen />, server.fetchImpl);
  await screen.findByText('Receta del día');
  expect(screen.getByRole('button', { name: 'Escanear ticket' }).props.accessibilityState.disabled).toBe(true);
  expect(screen.getByRole('button', { name: 'Chat' }).props.accessibilityState.disabled).toBe(true);
});

it('offers to create the menu when the week has none', async () => {
  const server = fakeApi({ 'GET /api/v1/profiles': [profile()], 'GET /api/v1/today': [], 'GET /api/v1/plans': null });
  await renderConnected(<TodayScreen />, server.fetchImpl);
  expect(await screen.findByText('Esta semana no tienes menú')).toBeTruthy();
  await fireEvent.press(screen.getByRole('button', { name: 'Crear menú' }));
  expect(router.push).toHaveBeenCalledWith('/menu/create');
});

it('says so when the week has a menu but nothing is planned today', async () => {
  const server = fakeApi({ 'GET /api/v1/profiles': [profile()], 'GET /api/v1/today': [], 'GET /api/v1/plans': plan(mondayOf(today()), []) });
  await renderConnected(<TodayScreen />, server.fetchImpl);
  expect(await screen.findByText('Hoy no hay comidas planificadas')).toBeTruthy();
});

it('lets a household with two people pick whose portions to see', async () => {
  const both = meal('lunch', 'Lentejas', today(), {
    portions: { Pablo: [{ product_id: 1, name: 'Lentejas', amount: '120', unit: 'g' }], Ana: [{ product_id: 1, name: 'Lentejas', amount: '80', unit: 'g' }] },
  });
  const server = fakeApi({ 'GET /api/v1/profiles': [profile('Pablo', 1), profile('Ana', 2)], 'GET /api/v1/today': [both], 'GET /api/v1/plans': plan(mondayOf(today()), [both]) });
  await renderConnected(<TodayScreen />, server.fetchImpl);
  expect(await screen.findByText('Lentejas 120 g')).toBeTruthy();
  await fireEvent.press(screen.getByRole('radio', { name: 'Ana' }));
  expect(await screen.findByText('Lentejas 80 g')).toBeTruthy();
});

it('explains a missing household and a refused token', async () => {
  const noHome = fakeApi({ 'GET /api/v1/profiles': () => apiError(409, 'setup_required', 'create the household first') });
  await renderConnected(<TodayScreen />, noHome.fetchImpl);
  expect(await screen.findByText('Falta crear el hogar.')).toBeTruthy();
  await fireEvent.press(screen.getByRole('button', { name: 'Ir a Ajustes' }));
  expect(router.push).toHaveBeenCalledWith('/settings');
});

it('shows a network error with retry', async () => {
  let up = false;
  const server = fakeApi({ 'GET /api/v1/profiles': () => (up ? [] : Promise.reject(new TypeError('offline'))) });
  const flaky = (request: Request) => server.fetchImpl(request);
  await renderConnected(<TodayScreen />, flaky);
  expect(await screen.findByText('No se puede conectar con el servidor.')).toBeTruthy();
  up = true;
  await fireEvent.press(screen.getByRole('button', { name: 'Reintentar' }));
  expect(await screen.findByText('Falta crear el hogar.')).toBeTruthy(); // empty profiles
});
