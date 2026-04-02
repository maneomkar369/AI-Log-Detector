# Android Build Guide (Behavioral Anomaly Detector)

## Prerequisites

- Android Studio Iguana+ (or latest stable)
- Android SDK Platform 34 installed
- JDK 17
- ADB available (`platform-tools`)
- Physical test device (Android 8.0+, API 26+)

## Open Project

1. Open Android Studio.
2. Select `AI_Log/android` as the project root.
3. Let Gradle sync finish.

## Run Debug Build

From Android Studio:
- Select app configuration.
- Click **Run** on connected device/emulator.

Or terminal:
```bash
cd android
./gradlew assembleDebug
```

## Build Release APK

```bash
cd android
./gradlew assembleRelease
```

Expected output path:
- `android/app/build/outputs/apk/release/app-release-unsigned.apk`

## Sign APK

```bash
jarsigner -verbose -sigalg SHA1withRSA -digestalg SHA1 \
  -keystore my-release-key.keystore \
  app/build/outputs/apk/release/app-release-unsigned.apk alias_name
```

## Align APK

```bash
zipalign -v -p 4 \
  app/build/outputs/apk/release/app-release-unsigned.apk \
  app/build/outputs/apk/release/app-release.apk
```

## Install on Device

```bash
adb install -r app/build/outputs/apk/release/app-release.apk
```

## Permission Validation Checklist

- Usage Stats permission granted
- Accessibility service enabled
- Notifications permission granted (Android 13+)
- Battery optimization disabled for app

## Current Scaffold Coverage

Implemented in this workspace:
- Manifest, permissions, foreground + accessibility services
- Room entities/DAO/database
- WebSocket manager + repository skeleton
- MainActivity + MainViewModel + basic UI

Not yet fully implemented:
- Full reconnect backoff strategy
- WorkManager sync worker and retry policy
- Complete alerts RecyclerView flow and approval dialog
- Hilt modules and dependency wiring
