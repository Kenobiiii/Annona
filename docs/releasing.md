# Building the Android app (APK)

> Verified once by the maintainer with the EAS `preview` profile (installed on an Android phone and
> connected to a home server). Follow the official
> [EAS Build documentation](https://docs.expo.dev/build/introduction/) if anything differs.

The signing key (keystore) belongs to **you**. It is never committed to the repository: EAS stores it
for you, or you keep your own. If you lose it you cannot update an installed app.

## Option 1: EAS (Expo cloud, recommended)

Requirements: a free [Expo account](https://expo.dev/signup), Node.js LTS.

```bash
cd app
npm ci
npx eas-cli login
npx eas-cli build --platform android --profile preview
```

The first run asks to generate an Android keystore: accept (EAS keeps it; download a backup with
`npx eas-cli credentials`). When it finishes you get a link to the signed `.apk`: open it on the
phone and allow installing from that source.

`preview` produces an installable APK. `production` produces an `.aab` for Google Play (needs a
developer account).

Plain HTTP (home network) is allowed by the app config (`usesCleartextTraffic`); prefer
[remote-access.md](remote-access.md) when away from home.

### Before the first build

Run `npx eas-cli init` once. It links the app to **your** Expo account and writes `owner` and
`extra.eas.projectId` into `app/app.json`. **Do not commit those two fields** (they belong to your
account and would break other people's builds); keep them local.

### Permissions

The app only needs the camera and photo library (to scan receipts). The `expo-image-picker` plugin
would also add the microphone permission for video; `app.json` sets `microphonePermission: false`,
so the APK does not ask for it. Check the merged permissions in the build log if you add plugins.

### First launch

The app asks for the server address and token: use `http://<computer-IP>:8000` on your home
network (the IP can change; update it in Settings) or your Tailscale address.

## Option 2: local build

Needs the Android SDK and JDK (see the Expo docs for "local builds"):
`npx eas-cli build --platform android --profile preview --local`.

## Releasing a version

1. Update the version (`pyproject.toml` files, `__version__`, `app/app.json`, `app/package.json`) and
   `CHANGELOG.md`.
2. Run the full checks (see CONTRIBUTING) from a fresh clone and wait for green CI.
3. `git tag v<version> && git push origin v<version>`.
