# FloraMW

A Flutter mobile frontend for a Malawi-focused botanical companion. Photograph a flower, explore a clearly labelled demonstration identification journey, browse source-linked reference profiles and keep a local field journal.

**Frontend only:** no backend services, live AI, server uploads, cloud sync or feedback submission are implemented or changed.

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
- Demonstration identification with loading, cancellation, candidate lists, no match, service error and retry. Demo candidates are independent of the selected photograph. No invented confidence score is shown.
- Reference profiles with licensed photographs, source links, scientific names/families, identifying features, plant care, growing conditions, toxicity, medicinal research and legal/conservation information.
- Scientific evidence and Malawian traditional knowledge remain separate. Malawi district occurrence, community-attributed uses and local names await field verification rather than being invented.
- Persistent bookmarks, discovery photos, district snapshots, history, editable notes and deletion.
- Correction form, local report drafts and draft deletion. Reports are not sent to a server.
- Language/district settings, dark mode, larger text, privacy/help/about, replay introduction and clear local records.
- Scrollable narrow-screen layouts, bundled fonts, accessible control tooltips, offline reference content and recoverable error states.

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
- `API_HANDOFF.md`: existing backend handoff requirements; no live API connection added.

Useful documentation: [Flutter](https://docs.flutter.dev/), [image_picker](https://pub.dev/packages/image_picker), [shared_preferences](https://pub.dev/packages/shared_preferences), [path_provider](https://pub.dev/packages/path_provider), [url_launcher](https://pub.dev/packages/url_launcher).
