# User Apps

Professional user-facing applications for the IAA Air Quality Monitoring platform. Both apps wrap the web frontend (served at port 3001) and add platform-specific features.

## Default Server

Both apps default to: **`https://www.talk2futurebuildings.systems:3001`**

Users can edit the server URL and port at any time in each app's settings.

---

## 1) Raspberry Pi Desktop App
**Path:** `User Apps/RPI app`

| | |
|---|---|
| **Technology** | Python + PySide6 + Qt WebEngine |
| **Default Server** | `https://www.talk2futurebuildings.systems:3001` |

### Features
- Embedded WebView UI (all tabs: Home, Data, Risk, Alerts, Ranking, Settings)
- Configurable server URL + port (separate fields)
- Connection test button with live status
- Branded splash screen
- Auto-reconnect on failure (30s interval)
- Wi-Fi scan/connect via `nmcli`
- Menu bar (File → Settings, Refresh, Wi-Fi, About, Quit)
- Custom error page with retry

### Install & Run
```bash
cd "User Apps/RPI app"
chmod +x install.sh
./install.sh        # Creates venv, installs deps, adds desktop launcher
```

Or manually:
```bash
cd "User Apps/RPI app"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python src/main.py
```

---

## 2) Android App
**Path:** `User Apps/Android/IAAUserApp`

| | |
|---|---|
| **Technology** | Native Android (Kotlin) + WebView |
| **Default Server** | `https://www.talk2futurebuildings.systems:3001` |
| **Min SDK** | Android 8.0 (API 26) |

### Features
- Full WebView UI with all IAA tabs
- Separate URL + port configuration
- Connection test with progress indicator
- Branded splash screen (1.5s)
- Pull-to-refresh (swipe down)
- Connection status bar (green/yellow/red)
- Error page with Retry + Edit Server Settings
- SSL certificate handling for dev environments
- GPS permission for web app registration
- Network security: HTTPS for production, cleartext for local dev

### Build
Open in Android Studio → Gradle sync → Build APK → Run on device/emulator.

---

## Server Connection

| Server | URL Example |
|--------|-------------|
| **Production** | `https://www.talk2futurebuildings.systems:3001` |
| **Local (RPI)** | `http://localhost:3001` |
| **Local (Android)** | `http://192.168.1.20:3001` (use your server's LAN IP) |
| **Emulator** | `http://10.0.2.2:3001` |
