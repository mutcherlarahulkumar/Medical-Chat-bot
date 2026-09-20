# Skin Tracker on Android

Two ways to get it on your phone. **Start with option 1** — it takes two
minutes, needs no build tools, and gives you a real home-screen app.

---

## Option 1 — Install as a PWA (recommended)

Skin Tracker ships as a Progressive Web App: an icon on your home screen, its
own window with no browser chrome, and an instant cold start.

1. **Start the server** on your computer:
   ```bash
   python run_skin_tracker.py
   ```
2. **Find your computer's IP** on the Wi-Fi network:
   ```bash
   hostname -I | awk '{print $1}'      # Linux
   ipconfig getifaddr en0              # macOS
   ipconfig                            # Windows — look for IPv4 Address
   ```
3. **On your Android phone**, on the same Wi-Fi, open Chrome and go to
   `http://<that-ip>:5001`.
4. Tap **Install on my phone** in the app, or Chrome's ⋮ menu →
   **Add to Home screen** / **Install app**.

That's it. It behaves like any other Android app.

### What works and what doesn't

| | |
|---|---|
| ✅ Home-screen icon, fullscreen, portrait | |
| ✅ Camera — the photo button opens your real camera | |
| ✅ App shell cached, so it opens instantly and survives a dropped connection | |
| ⚠️ **Your photos and timeline need the server running.** They live on your computer, not the phone. | |
| ⚠️ Only on the same Wi-Fi, unless you expose the server (see below) | |

### Using it away from home

The server has no login on it, so don't put it straight onto the public
internet. Two reasonable options:

- **Tailscale** (easiest) — install it on your computer and your phone, then
  use the computer's Tailscale IP instead of the LAN IP. Encrypted, private to
  your devices, works from anywhere.
- **A cheap VPS** — run the same Flask app behind HTTPS with a password. More
  work; only worth it if you want it always-on.

---

## Option 2 — Build a real APK with Capacitor

Worth it only if you want to sideload an `.apk`, put it on the Play Store, or
reach native APIs the browser doesn't expose. The app itself is identical —
Capacitor wraps the same page in a native shell.

### You'll need

- [Android Studio](https://developer.android.com/studio) (brings the Android
  SDK and an emulator)
- Node.js 22+
- A JDK 21 (Android Studio ships one)

### Steps

```bash
cd mobile
npm install
```

Now **edit `capacitor.config.json`** and replace `192.168.1.10` with your
computer's actual IP from step 2 above. This is the one step people miss — the
app will show "Can't reach your Skin Tracker server" if it's wrong.

```bash
npx cap add android      # generates the native project in mobile/android/
npx cap sync android
npx cap open android     # opens Android Studio
```

In Android Studio: **Run ▶** to install on a connected phone or emulator, or
**Build → Build Bundle(s)/APK → Build APK(s)** for a shareable file. From the
command line, once the SDK is set up:

```bash
cd android && ./gradlew assembleDebug
# → android/app/build/outputs/apk/debug/app-debug.apk
```

`mobile/android/` is gitignored — it's generated, so regenerate it with
`npx cap add android` rather than committing it.

### Why cleartext HTTP is enabled

`"cleartext": true` lets the app talk to `http://` on your LAN, which Android
otherwise blocks. That's fine for a server on your own Wi-Fi. If you ever put
Skin Tracker on the public internet, put HTTPS in front of it and remove that
flag.

---

## Option 3 — a fully offline native app

If you want the photos stored *on the phone* with no server at all, that's a
genuine rewrite (React Native or Flutter, with SQLite on-device and the Claude
call moved behind a small hosted endpoint — an API key must never ship inside
an app). Say the word if that's the direction you want.
