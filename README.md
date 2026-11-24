# FloraMW

A Flutter mobile app for a Malawi-focused flower companion, backed by the FloraMW FastAPI service. Browse the server-managed flower catalogue and profiles, request photo identification through the configured backend provider, submit botanical corrections, and keep an offline-first field journal.

## Run

Use Flutter **3.47.9**, a compatible Android SDK/Java setup, or macOS/Xcode for iOS. Native Android and iOS runner projects are included.

```sh
flutter pub get --enforce-lockfile
flutter analyze --no-pub
flutter test --no-pub
flutter run
```

For an installable development build:

```sh
flutter build apk --debug --no-pub
```

The APK is created at `build/app/outputs/flutter-apk/app-debug.apk`. Production signing is deliberately separate; see [release instructions](docs/RELEASE.md). No production signing key is included. Camera/gallery testing needs a configured device.

## Frontend features

- Branded native launch screens, app icons, welcome pages and first-run district/language setup.
- Searchable list of all 28 Malawi districts, grouped by region. The selected district persists and is recorded with discoveries; no GPS permission is requested.
- Discover search by common name, scientific name or family, categories, sorting and empty/reset state.
- Camera/gallery selection, photo preview/removal, consent explanation, permission failures and Android lost-image recovery.
- Backend photo identification with explicit upload consent, provider metadata, safety disclaimer, candidate/no-match states and retry. When the backend is configured with a demonstration provider, results are visibly labelled as examples and never presented as photo predictions.
- Reference profiles with licensed photographs, source links, scientific names/families, flower features, flower care, growing conditions, toxicity, medicinal research and legal/conservation information.
- Scientific evidence and Malawian traditional knowledge remain separate. Malawi district occurrence, community-attributed uses and local names await field verification rather than being invented.
- Persistent bookmarks, discovery photos, district snapshots, history, editable notes and deletion.
- Botanical correction reports submitted to the backend, with local draft fallback when the service is unavailable.
- Language/district settings, dark mode, larger text, privacy/help/about, replay introduction and clear local records.
- Scrollable narrow-screen layouts, bundled fonts, accessible control tooltips, offline reference content and recoverable error states.

## Backend connection

The Flutter app uses the FastAPI service for the flower catalogue, full flower profiles, photo identification, botanical reports and field-journal synchronization. Configure the backend URL at build time; release builds intentionally refuse to fall back to localhost:

```sh
flutter run --dart-define=FLORAMW_API_BASE_URL=https://your-api-host
flutter build apk --release --dart-define=FLORAMW_API_BASE_URL=https://your-api-host
```

Use the deployed HTTPS API origin only (without `/api/v1`). Keep provider API keys on the server, never in Flutter. The identification endpoint must be configured with a real provider and `ALLOW_MOCK_PROVIDER=false` in production. A mock provider response is marked as demonstration data in the app. Journal notes and district/flower metadata sync through the offline outbox; selected photos remain on the device and are not uploaded as journal attachments. See [backend integration guide](backend/FLORAMW_BACKEND_INTEGRATION_GUIDE.md).

## Language status

The language selector and translation framework cover **English, Chichewa, Yao, Tumbuka, Sena, Lhomwe and Tonga**. Chichewa includes draft navigation wording. Full translations are **not complete**; unreviewed/missing phrases fall back to English with a visible notice.

Settings → Language packs & translation review displays available/missing interface phrases and supports persistent local wording edits. This is an authoring/review aid, not a claim of translation accuracy or a remote submission system. See [localization guidance](LOCALIZATION.md).

## Content and image sources

General botanical summaries link to NC State Extension, Kew and Singapore National Parks. Periwinkle research links to the US National Cancer Institute; safety information links to Queensland Health and the University of California. Malawi medicine-regulation context links to PMRA. These are educational summaries, not personalized medical advice, a botanist-confirmed identification or permission to harvest/sell plants.

Photographs are bundled under their stated Creative Commons licences, with on-screen author/source/licence links. See [image and font notices](THIRD_PARTY_NOTICES.md). The selected district and a reference photograph do not establish that a species occurs locally.

## Validation

- Flutter analysis and local widget/state/layout/screenshot checks are exercised by the included test suite.
- Standalone model checks: `dart tool/check_models.dart`.
- Asset/licence/native-metadata checks: `python3 tool/check_assets.py`.
- GitHub Actions workflow: [frontend.yml](.github/workflows/frontend.yml). It verifies the frontend, builds a debug Android APK and prepares an unsigned iOS simulator build. It does not publish or change a backend.
- Checked-in screenshots are Flutter test-rendered references, not physical-device screenshots: [Discover](docs/screenshots/discover.png), [Identify](docs/screenshots/identify.png), [Plant profile](docs/screenshots/profile.png).

See [current validation results](docs/VALIDATION.md) and the [device acceptance checklist](QA_CHECKLIST.md). Physical camera/gallery behavior, screen readers, representative low-end devices, iOS signing and App Store publication require separate device/platform validation.

## Structure

- `lib/main.dart`: startup, themes, onboarding, home shell and discovery.
- `lib/preferences.dart`, `lib/locale_data.dart`: district/language setup and identifiers.
- `lib/localization.dart`, `assets/translations.json`: translated text and fallback.
- `lib/models.dart`: reference catalogue, journal models and unchanged demo identification interface.
- `lib/store.dart`: local persistence and app-owned photo lifecycle.
- `lib/screens/`: identify, profiles/corrections, journal, settings and language review.
- `android/`, `ios/`: native frontend runners and permission/build configuration.
- `test/`, `tool/`: automated checks, visual references and branding helper.
- `API_HANDOFF.md`: API contract, deployment configuration and remaining operational requirements.

Useful documentation: [Flutter](https://docs.flutter.dev/), [image_picker](https://pub.dev/packages/image_picker), [shared_preferences](https://pub.dev/packages/shared_preferences), [path_provider](https://pub.dev/packages/path_provider), [url_launcher](https://pub.dev/packages/url_launcher).
