// SPDX-License-Identifier: AGPL-3.0-or-later
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { unwrap, type Schemas } from './client';
import { useApi } from './providers';

export const keys = {
  household: ['household'] as const,
  profiles: ['profiles'] as const,
  equipment: ['equipment'] as const,
  pantry: ['pantry'] as const,
  products: (q: string, store?: string) => ['products', q, store ?? ''] as const,
  product: (id: number) => ['product', id] as const,
  plan: (week: string) => ['plan', week] as const,
  today: (day: string, profileId?: number) => ['today', day, profileId ?? 0] as const,
  shopping: (planId: number) => ['shopping', planId] as const,
  catalog: ['catalog-stores'] as const,
  job: (id: string) => ['job', id] as const,
  llm: ['llm-settings'] as const,
  recipe: (day: string, slot: string) => ['recipe', day, slot] as const,
  cookPreview: (day: string, slot: string) => ['cook-preview', day, slot] as const,
};

// ---- reads ---------------------------------------------------------------------------------

export function useHousehold() {
  const api = useApi();
  return useQuery({ queryKey: keys.household, queryFn: () => unwrap(api.GET('/api/v1/household')) });
}

export function useProfiles() {
  const api = useApi();
  return useQuery({ queryKey: keys.profiles, queryFn: () => unwrap(api.GET('/api/v1/profiles')) });
}

export function useEquipment() {
  const api = useApi();
  return useQuery({ queryKey: keys.equipment, queryFn: () => unwrap(api.GET('/api/v1/equipment')) });
}

export function usePantry() {
  const api = useApi();
  return useQuery({
    queryKey: keys.pantry,
    queryFn: () => unwrap(api.GET('/api/v1/pantry', { params: { query: { page: 1, size: 200 } } })),
  });
}

export function useSearchProducts(q: string, store?: string) {
  const api = useApi();
  return useQuery({
    queryKey: keys.products(q, store),
    enabled: q.trim().length >= 2,
    queryFn: () =>
      unwrap(api.GET('/api/v1/products', { params: { query: { q: q.trim(), store, page: 1, size: 30 } } })),
  });
}

export function useProduct(id: number) {
  const api = useApi();
  return useQuery({
    queryKey: keys.product(id),
    queryFn: () => unwrap(api.GET('/api/v1/products/{product_id}', { params: { path: { product_id: id } } })),
  });
}

export function usePlan(week: string) {
  const api = useApi();
  return useQuery({
    queryKey: keys.plan(week),
    queryFn: () => unwrap(api.GET('/api/v1/plans', { params: { query: { week } } })),
  });
}

export function useToday(day: string, profileId?: number) {
  const api = useApi();
  return useQuery({
    queryKey: keys.today(day, profileId),
    queryFn: () => unwrap(api.GET('/api/v1/today', { params: { query: { day, profile_id: profileId } } })),
  });
}

export function useShoppingList(planId: number | undefined) {
  const api = useApi();
  return useQuery({
    queryKey: keys.shopping(planId ?? 0),
    enabled: planId !== undefined,
    queryFn: () =>
      unwrap(api.GET('/api/v1/plans/{plan_id}/shopping-list', { params: { path: { plan_id: planId! } } })),
  });
}

export function useCatalogStores() {
  const api = useApi();
  return useQuery({ queryKey: keys.catalog, queryFn: () => unwrap(api.GET('/api/v1/catalog/stores')) });
}

export function useLlmSettings() {
  const api = useApi();
  return useQuery({ queryKey: keys.llm, queryFn: () => unwrap(api.GET('/api/v1/settings/llm')) });
}

/** Polls a background job every 2 s until it is done or failed. */
export function useJob(jobId: string | undefined) {
  const api = useApi();
  return useQuery({
    queryKey: keys.job(jobId ?? ''),
    enabled: !!jobId,
    queryFn: () => unwrap(api.GET('/api/v1/jobs/{job_id}', { params: { path: { job_id: jobId! } } })),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'done' || status === 'failed' ? false : 2000;
    },
  });
}

// ---- writes --------------------------------------------------------------------------------

type Invalidate = readonly (readonly unknown[])[];

function useWrite<TVars, TData>(run: (vars: TVars) => Promise<TData>, invalidate: Invalidate) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: async () => {
      await Promise.all(invalidate.map((queryKey) => queryClient.invalidateQueries({ queryKey })));
    },
  });
}

export function usePutHousehold() {
  const api = useApi();
  return useWrite(
    (body: Schemas['HouseholdIn']) => unwrap(api.PUT('/api/v1/household', { body })),
    [keys.household, keys.profiles],
  );
}

export function useSaveProfile() {
  const api = useApi();
  return useWrite(
    ({ id, body }: { id?: number; body: Schemas['ProfileIn'] }) =>
      id === undefined
        ? unwrap(api.POST('/api/v1/profiles', { body }))
        : unwrap(api.PUT('/api/v1/profiles/{profile_id}', { params: { path: { profile_id: id } }, body })),
    [keys.profiles],
  );
}

export function useDeleteProfile() {
  const api = useApi();
  return useWrite(
    (id: number) => unwrap(api.DELETE('/api/v1/profiles/{profile_id}', { params: { path: { profile_id: id } } })),
    [keys.profiles],
  );
}

export function usePutEquipment() {
  const api = useApi();
  return useWrite(
    (body: Schemas['EquipmentIn']) => unwrap(api.PUT('/api/v1/equipment', { body })),
    [keys.equipment],
  );
}

export function useSavePantryItem() {
  const api = useApi();
  return useWrite(
    ({ id, body }: { id?: number; body: Schemas['PantryIn'] }) =>
      id === undefined
        ? unwrap(api.POST('/api/v1/pantry', { body }))
        : unwrap(api.PUT('/api/v1/pantry/{item_id}', { params: { path: { item_id: id } }, body })),
    [keys.pantry],
  );
}

export function useDeletePantryItem() {
  const api = useApi();
  return useWrite(
    (id: number) => unwrap(api.DELETE('/api/v1/pantry/{item_id}', { params: { path: { item_id: id } } })),
    [keys.pantry],
  );
}

/** Only the fields given change (the generated type wrongly asks for ``allergens_unknown``). */
type ProductChanges = Partial<Schemas['ProductPatch']>;

export function usePatchProduct(id: number) {
  const api = useApi();
  return useWrite(
    (changes: ProductChanges) =>
      unwrap(
        api.PATCH('/api/v1/products/{product_id}', {
          params: { path: { product_id: id } },
          body: { allergens_unknown: false, ...changes },
        }),
      ),
    [keys.product(id), ['products'], keys.pantry],
  );
}

export function useGeneratePlan() {
  const api = useApi();
  return useMutation({
    mutationFn: (body: Schemas['PlanIn']) => unwrap(api.POST('/api/v1/plans', { body })),
  });
}

export function useCheckShoppingItem(planId: number) {
  const api = useApi();
  return useWrite(
    ({ id, checked }: { id: number; checked: boolean }) =>
      unwrap(
        api.PATCH('/api/v1/shopping-items/{item_id}', {
          params: { path: { item_id: id } },
          body: { checked },
        }),
      ),
    [keys.shopping(planId)],
  );
}

// ---- recipes and cooking -------------------------------------------------------------------

type Slot = Schemas['MealSlot'];

/** The detailed recipe of a planned meal. The first call may take 10-30 s (the AI writes it). */
export function useRecipe(day: string, slot: Slot) {
  const api = useApi();
  return useQuery({
    queryKey: keys.recipe(day, slot),
    staleTime: Infinity,
    retry: false,
    queryFn: () => unwrap(api.POST('/api/v1/meals/recipe', { body: { day, slot, regenerate: false } })),
  });
}

export function useRegenerateRecipe(day: string, slot: Slot) {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/meals/recipe', { body: { day, slot, regenerate: true } })),
    onSuccess: (recipe) => queryClient.setQueryData(keys.recipe(day, slot), recipe),
  });
}

/** What marking the meal as cooked would take from the pantry (changes nothing). */
export function useCookPreview(day: string, slot: Slot, enabled: boolean) {
  const api = useApi();
  return useQuery({
    queryKey: keys.cookPreview(day, slot),
    enabled,
    gcTime: 0,
    queryFn: () => unwrap(api.GET('/api/v1/meals/cook-preview', { params: { query: { day, slot } } })),
  });
}

export function useCookMeal(day: string, slot: Slot) {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (skipProducts: number[]) =>
      unwrap(api.POST('/api/v1/meals/cook', { body: { day, slot, skip_products: skipProducts } })),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.pantry }),
        queryClient.invalidateQueries({ queryKey: keys.recipe(day, slot) }),
        queryClient.invalidateQueries({ queryKey: keys.cookPreview(day, slot) }),
      ]);
    },
  });
}
