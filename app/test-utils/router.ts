// SPDX-License-Identifier: AGPL-3.0-or-later
export const router = {
  push: jest.fn(),
  replace: jest.fn(),
  back: jest.fn(),
  canGoBack: jest.fn(() => true),
  setParams: jest.fn(),
};

export function resetRouter() {
  Object.values(router).forEach((fn) => fn.mockClear());
}
