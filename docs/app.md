# The Annona app

Expo (React Native) app for Android. It needs a running Annona server ([self-hosting](self-hosting.md)):
on first launch it asks for the server address and the API token, tests the connection and stores
both in the device's secure storage. The AI key is **never** entered in the app; it lives in the
server `.env`, and Settings only shows which models are configured and whether their key is present.

## Development

1. Start the server (`docker compose up`, or `uv run uvicorn ...`; see self-hosting).
2. `cd app && npm ci && npm start`.
3. Browser preview: press `w` (or `npm run web`). The browser enforces CORS, so start the server with
   `ANNONA_CORS_ORIGINS=http://localhost:8081`.
4. Phone: install Expo Go and scan the QR code. The phone must reach the server over the network
   (same Wi-Fi). Use the computer's LAN address, e.g. `http://192.168.1.20:8000`.

### Server inside WSL2 on Windows

WSL2 uses a private network by default, so a phone cannot reach it. Options (not yet verified on
the project author's machine; check Microsoft's WSL networking documentation first):
mirrored networking (`networkingMode=mirrored` in `%UserProfile%\.wslconfig`, then `wsl --shutdown`)
plus a Windows firewall rule for the server port, or run the server on the Windows side/another host.
This changes Windows settings, so do it deliberately.

## Plain HTTP

Until HTTPS arrives (Phase 15), a release APK must allow cleartext traffic to reach a LAN server.
The app enables this through `expo-build-properties` (`usesCleartextTraffic`); the connection form
warns when the address is not HTTPS. Do not expose the server to the internet over plain HTTP.

## Building an APK

Not yet executed in this project; the standard routes from the Expo documentation are:

- **Local**: install Android Studio (SDK) and JDK 17, then `npx expo prebuild --platform android`
  and build the release variant with Gradle in `android/`.
- **EAS Build**: an Expo account and `eas build -p android --profile preview` (an `eas.json` with an
  APK profile is needed).

Verify the exact steps against the current Expo docs for SDK 58 before relying on them.
