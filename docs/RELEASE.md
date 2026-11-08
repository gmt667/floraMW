# Frontend build and release

This repository contains the Flutter client and native Android/iOS runner source only. No backend services, live identification requests, cloud feedback submission or authentication service have been added.

## Development build

Use Flutter 3.47.9 (the version used for the checked-in lockfile and CI), Java 21, Android SDK 36 and the SDK components required by Flutter. Minimum targets in this generated project: Android API 24 and iOS 15. Follow the plugin documentation if changing these targets.

```sh
flutter pub get --enforce-lockfile
flutter analyze --no-pub
flutter test --no-pub
flutter build apk --debug --no-pub
```

The debug APK is at `build/app/outputs/flutter-apk/app-debug.apk`. This is a development-signed demonstration build, not a Play Store release. Camera, gallery permissions, OS backup and physical-device behavior must still be tested on real devices.

Use normal developer environment configuration locally. On managed build hosts, CI=true / BOT=true prevents Flutter's automatic cloud metadata probe, and FLUTTER_SUPPRESS_ANALYTICS=true disables tool analytics. These environment settings affect development tools, not application functionality.

## Android production signing

Release builds require your own signing identity. Copy `android/key.properties.example` to the ignored `android/key.properties` and fill in the path and credentials for your private upload key. Confirm the application ID before publishing. The Gradle configuration deliberately does not silently sign a release using the debug key.

```sh
flutter build appbundle --release
```

Do not commit signing files, passwords, generated app packages, or service credentials. No production key is included or created by this project.

## iOS

Use macOS with compatible Xcode and Flutter installed. The repository includes the Xcode project and permission descriptions. Local Linux checks cannot validate Xcode compilation, signing, physical camera behavior or App Store distribution.

```sh
flutter pub get --enforce-lockfile
flutter build ios --simulator --debug --no-codesign
```

For device distribution, open `ios/Runner.xcworkspace`, configure your Apple development team and signing, then follow Flutter's iOS release instructions. The GitHub workflow contains an unsigned simulator compilation job; it does not publish an app or configure production signing.

## Before public release

Complete native-speaker translation review, botanical/local-knowledge review and legal-content review; test screen readers and representative physical devices; replace the demo identification service only when a backend contract and explicit upload-consent flow are approved. No selected language, district or reference photograph should be treated as a verified plant identification.
