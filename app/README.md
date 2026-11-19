# annona-app

Android-first Expo (React Native, TypeScript) client for Annona. Currently the blank Expo template;
screens and navigation arrive in a later phase.

Requirements: Node.js current LTS (see the `expo` docs for the supported range).

```bash
npm ci
npm start            # Expo dev server (scan the QR code with Expo Go)
npm run lint         # eslint (eslint-config-expo)
npm run typecheck    # tsc --noEmit
npm test             # jest (jest-expo preset)
```

Add Expo/React Native packages with `npx expo install <pkg>` so versions match the SDK.
See [AGENTS.md](AGENTS.md) for notes on working with the current Expo SDK.
