# FloraMW build and release

## Configure the backend

The Flutter client uses the FloraMW FastAPI service for the flower catalogue and full profiles, photo identification, botanical reports and field-journal metadata synchronization.

Set the API origin at build time. Do not append `/api/v1`:

```sh
flutter run --dart-define=FLORAMW_API_BASE_URL=https://your-api-host
flutter build apk --release --dart-define=FLORAMW_API_BASE_URL=https://your-api-host
```

Release builds require a valid HTTPS origin and fail fast if the define is missing. Development builds can use Android emulator/localhost defaults. Provider credentials belong only in the backend environment; never bundle them in Flutter.

Before release, configure a real identification provider and disable mock mode in production. A mock/deterministic response is visibly labelled as a demonstration in the app. Photo identification asks for consent before uploading the selected image to the backend/provider. Confirm that the deployed provider's retention policy matches the app's privacy and consent wording.

The field journal synchronizes flower ID, timestamp, district, notes and demo/live status. Journal photos remain on the device; photo attachment upload is not implemented. Correction reports are submitted to the backend, with local drafts retained if submission fails.

## Development validation

Use Flutter 3.47.9 (the version used for the checked-in lockfile and CI), Java 21, Android SDK 36 and the SDK components required by Flutter.

```sh
flutter pub get --enforce-lockfile
dart format --output=none --set-exit-if-changed lib test tool/check_models.dart
flutter analyze --no-pub
flutter test --no-pub
dart tool/check_models.dart
python3 tool/check_assets.py
flutter build apk --debug --no-pub
```

The debug APK is at `build/app/outputs/flutter-apk/app-debug.apk`. It is a development build, not a Play Store release. Camera/gallery permissions, physical-device behavior, network connectivity and server/provider behavior must be tested on actual devices and the deployed API.

## Android production signing

Release builds require your own signing identity. Copy `android/key.properties.example` to the ignored `android/key.properties` and fill in the path and credentials for your private upload key. Confirm the application ID before publishing.

```sh
flutter build appbundle --release --dart-define=FLORAMW_API_BASE_URL=https://your-api-host
```

Do not commit signing files, passwords, generated app packages or service credentials. No production key is included.

## iOS

Use macOS with compatible Xcode and Flutter installed. The repository includes the Xcode project and permission descriptions.

```sh
flutter pub get --enforce-lockfile
flutter build ios --simulator --debug --no-codesign --dart-define=FLORAMW_API_BASE_URL=https://your-api-host
```

For device distribution, open `ios/Runner.xcworkspace`, configure your Apple development team and signing, then follow Flutter's iOS release instructions. GitHub Actions prepares an unsigned simulator build; it does not publish an app or configure production signing.

## Production smoke test

Verify the configured API host before release:

- `GET /health`
- `POST /api/v1/auth/anonymous`
- `GET /api/v1/flowers`
- `GET /api/v1/flowers/hibiscus`
- `POST /api/v1/identifications` with an approved test image
- Create, update and delete a field-journal observation
- Submit a botanical correction report

Do not claim production integration is complete until these requests succeed against the actual deployed host and the configured identification provider returns non-demo results.
