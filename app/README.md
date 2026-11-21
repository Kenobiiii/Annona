# annona-app

Android-first Expo (React Native, TypeScript) client for Annona. It talks to your own Annona server
and contains no business logic: calories, prices and menus are computed by the server.

Screens: Today (recipe of the day), Products (pantry + search), Weekly menu, Tools (kitchen),
Shopping list, Settings (server, household, people, AI status). Spanish first; texts live in
`src/i18n/es.ts` so more languages can be added. Light/dark mode and system text size are supported.

Requirements: Node.js current LTS.

```bash
npm ci
npm start            # Expo dev server (Expo Go on a phone, or press "w" for the browser)
npm run web          # browser preview (needs ANNONA_CORS_ORIGINS=http://localhost:8081 on the server)
npm run lint         # eslint
npm run typecheck    # tsc --noEmit
npm test             # jest
npm run gen:api      # regenerate src/api/schema.d.ts from src/api/openapi.json
```

The API types come from the server's OpenAPI schema. After changing the server API run
`uv run python scripts/export_openapi.py` (repository root) and then `npm run gen:api`; CI fails if
the committed files are stale.

Add Expo/React Native packages with `npx expo install <pkg>` so versions match the SDK.
See [AGENTS.md](AGENTS.md) and [../docs/app.md](../docs/app.md) (running on a phone, building the APK).
