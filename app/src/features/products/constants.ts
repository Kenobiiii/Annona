// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Schemas } from '@/api/client';

/** The 14 allergens that must be declared in the EU, in the server's order. */
export const ALLERGENS: Schemas['Allergen'][] = [
  'gluten', 'crustaceans', 'eggs', 'fish', 'peanuts', 'soybeans', 'milk',
  'nuts', 'celery', 'mustard', 'sesame', 'sulphites', 'lupin', 'molluscs',
];

export const UNITS: Schemas['Unit'][] = ['g', 'ml', 'unit'];
