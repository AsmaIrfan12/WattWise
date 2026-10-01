# WattWise User App (Android)

Native Android application for the WattWise platform. It hosts the user dashboard in an enhanced WebView and adds native reliability, settings, and notification routing on top.

## Default Server

Production: `https://www.talk2futurebuildings.systems` (port 443)
Local dev: `http://<server-ip>:3001` (user frontend container)

Change anytime via the ⚙ Settings button.

## User Features

| Area | Capability |
|-----|-------------|
| Dashboard | Household usage view, trend chart, ranking, and alerts preview |
| Devices | Device list and onboarding flow for configured home |
| Notifications | Actionable alerts routed from backend notifications |
| Goals | Goal setup and progress tracking |
| Ranking | Community leaderboard and personal score breakdown |
| Settings | Runtime server URL/port and connectivity testing |

## Native Android Enhancements

- Dynamic server URL routing without Retrofit rebuild
- Pull-to-refresh and resilient WebView error handling
- Push notification deep-link routing into dashboard pages
- Runtime permission handling (network/location/notifications)
- Debug-only SSL error bypass with production-safe cancellation

## Build

1. Open `User Apps/Android/WattWiseUserApp` in Android Studio
2. Wait for **Gradle sync** to complete (bottom progress bar)
3. **Build** → **Build Bundle(s) / APK(s)** → **Build APK(s)**
4. Click **"locate"** in the notification to find `app-debug.apk`
5. Install on device or run via emulator

## Permissions Required

| Permission | Why |
|-----------|-----|
| INTERNET | Connect to WattWise backend and dashboards |
| ACCESS_NETWORK_STATE | Detect WiFi vs Mobile Data vs offline |
| ACCESS_WIFI_STATE | Show WiFi connection details |
| ACCESS_FINE_LOCATION | GPS for device registration page |

## Package Identity

- Namespace: `com.wattwise.userapp`
- Application ID: `com.wattwise.userapp`
