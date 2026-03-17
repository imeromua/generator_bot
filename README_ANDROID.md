# ServiceDesk Android App — Build Guide

Native Android wrapper for the **ServiceDesk PWA** using
[Trusted Web Activity (TWA)](https://developer.chrome.com/docs/android/trusted-web-activity/).

## Architecture

```
android-app/
├── app/
│   └── src/main/
│       ├── java/ua/imero/servicedesk/
│       │   ├── MainActivity.kt     ← TWA launcher with WebView fallback
│       │   └── SplashActivity.kt   ← Minimal splash screen
│       ├── res/
│       │   ├── drawable/           ← Launcher icons
│       │   ├── values/
│       │   │   ├── strings.xml     ← base_url, app_name
│       │   │   └── themes.xml      ← Full-screen / NoActionBar themes
│       │   └── xml/
│       │       └── network_security_config.xml  ← HTTPS-only policy
│       └── AndroidManifest.xml
├── build.gradle
├── settings.gradle
└── gradle.properties
```

**TWA** uses the Chrome engine installed on the device, providing full PWA
support (Service Worker, localStorage, Web Push, etc.) without shipping an
extra browser engine in the APK.  
A **WebView fallback** is used when Chrome / Custom Tabs are not available.

---

## Prerequisites

| Tool | Minimum version |
|------|----------------|
| Android Studio | Hedgehog (2023.1.1) or newer |
| Android SDK | API 34 (compileSdk) |
| Kotlin | 1.9.x |
| JDK | 17 |

---

## Step 1 — Set the Service URL

Open `app/src/main/res/values/strings.xml` and replace `REPLACE_WITH_YOUR_DOMAIN` with your actual hostname:

```xml
<string name="base_url">https://example.com/sd/</string>
<string name="asset_statements">
    [{"include": "https://example.com/.well-known/assetlinks.json"}]
</string>
```

> The URL **must** use HTTPS. Cleartext HTTP is blocked by
> `network_security_config.xml` and the manifest attribute
> `android:usesCleartextTraffic="false"`.
>
> **Don't forget:** if you leave `REPLACE_WITH_YOUR_DOMAIN` in the strings
> file the app will attempt to load an unreachable URL.

---

## Step 2 — Build a Debug APK

```bash
cd android-app
./gradlew assembleDebug
```

The output APK is located at:

```
app/build/outputs/apk/debug/app-debug.apk
```

Install it on a connected device or emulator:

```bash
adb install app/build/outputs/apk/debug/app-debug.apk
```

---

## Step 3 — Digital Asset Links (TWA verification)

TWA requires proof that the Android app and the web server belong to the same
owner. This is done via a **Digital Asset Links** JSON file hosted on the
server.

### 3a. Generate a release keystore

```bash
keytool -genkey -v \
  -keystore release.jks \
  -alias servicedesk \
  -keyalg RSA -keysize 2048 \
  -validity 10000
```

### 3b. Get the SHA-256 fingerprint

```bash
keytool -list -v -keystore release.jks -alias servicedesk
```

Copy the **SHA-256** fingerprint (format: `AA:BB:CC:…`).

### 3c. Update the server endpoint

The FastAPI backend already exposes `/.well-known/assetlinks.json`.  
Open `servicedesk/static_router.py` and replace the placeholder:

```python
_PLACEHOLDER_SHA256 = "AA:BB:CC:..."  # paste your real fingerprint here
```

Redeploy the server and verify:

```
curl https://your-domain.com/.well-known/assetlinks.json
```

### 3d. Update strings.xml

The `asset_statements` string in `strings.xml` should already point to your
domain. No change needed if Step 1 was completed.

---

## Step 4 — Build a Release APK

### 4a. Create `keystore.properties` (do **not** commit this file)

```
storeFile=../release.jks
storePassword=YOUR_STORE_PASS
keyAlias=servicedesk
keyPassword=YOUR_KEY_PASS
```

### 4b. Reference the keystore in `app/build.gradle`

Add a `signingConfigs` block inside the `android {}` closure:

```groovy
signingConfigs {
    release {
        def props = new Properties()
        props.load(new FileInputStream(rootProject.file("keystore.properties")))
        storeFile     file(props['storeFile'])
        storePassword props['storePassword']
        keyAlias      props['keyAlias']
        keyPassword   props['keyPassword']
    }
}
buildTypes {
    release {
        signingConfig signingConfigs.release
        // ... (minifyEnabled etc. already present)
    }
}
```

### 4c. Assemble

```bash
./gradlew assembleRelease
```

Output: `app/build/outputs/apk/release/app-release.apk`

---

## Launcher Icons

Place your icon files in `app/src/main/res/drawable/`:

| File | Size | Usage |
|------|------|-------|
| `ic_launcher.png` | 192 × 192 px | Standard launcher icon |
| `ic_launcher_round.png` | 192 × 192 px | Round launcher icon (Android 7.1+) |

Use [Android Asset Studio](https://romannurik.github.io/AndroidAssetStudio/icons-launcher.html)
to generate adaptive icons at all required densities.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| App shows white screen | `base_url` unreachable | Check URL and network connectivity |
| TWA shows browser toolbar | Domain not verified | Check `assetlinks.json` is reachable and fingerprint matches |
| Build fails — SDK not found | SDK path not set | Set `ANDROID_HOME` env var or create `local.properties` |
| `CLEARTEXT communication not permitted` | HTTP URL used | Switch to HTTPS |
