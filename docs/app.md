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

WSL2 uses a private network by default, so a phone cannot reach it. Verified working on Windows 11
(22H2 or newer is required) with mirrored networking, following Microsoft's
[WSL networking documentation](https://learn.microsoft.com/en-us/windows/wsl/networking):

1. Create `%UserProfile%\.wslconfig` (PowerShell: `Set-Content -Path "$env:USERPROFILE\.wslconfig"
   -Value "[wsl2]","networkingMode=mirrored" -Encoding ASCII`; if the file exists, add the line
   under `[wsl2]` instead).
2. In an administrator PowerShell, open the Hyper-V firewall for the server (8000) and for Expo's
   Metro bundler (8081), using the VM creator id from the documentation:
   `New-NetFirewallHyperVRule -Name "Annona" -DisplayName "Annona server" -Direction Inbound
   -VMCreatorId '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -Protocol TCP -LocalPorts 8000`
   (repeat with another name and `-LocalPorts 8081`).
3. `wsl --shutdown`, then open WSL again. WSL now shows your LAN address (`ip -4 addr`).
4. Start the server listening on all interfaces (`--host 0.0.0.0`, the Docker image already does)
   and Metro with `REACT_NATIVE_PACKAGER_HOSTNAME=<LAN address> npx expo start --lan`.
5. On the phone (same Wi-Fi): check `http://<LAN address>:8000/health`, open
   `exp://<LAN address>:8081` in Expo Go, then enter `http://<LAN address>:8000` and the token in
   the connection form.

Tip: use a token without look-alike characters (`python -c "import secrets; print(secrets.token_hex(8))"`);
typing a random token on a phone keyboard is error-prone.

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
