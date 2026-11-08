# FloraMW — Flutter mobile frontend

A Malawi-focused, offline-first frontend for Android and iOS. Forest-green Material 3 styling, camera/gallery capture, complete demonstration identification journey, structured plant profiles and a persistent local field journal.

## Run on your computer

Install the Flutter stable SDK and Android Studio (Android) or Xcode on macOS (iOS). From this project folder:

```sh
flutter create --platforms=android,ios --org mw.floramw --project-name floramw --no-pub .
flutter pub get
python -m pip install pillow
python tool/brand_platforms.py
flutter analyze
flutter test
flutter run
```

These commands generate the standard native runner projects locally. Retain the supplied `lib`, `assets`, `test` and `pubspec.yaml`; do not use `flutter create --overwrite`. `brand_platforms.py` applies FloraMW launcher icons, launch-screen branding and iOS camera/photo descriptions to generated runners. It uses the supplied `assets/icon.png`. Camera testing requires a configured physical device. The app itself shows branded startup, welcome and setup screens.

To produce an Android package after device validation:

```sh
flutter build apk --release
```

An iOS archive must be built and signed on macOS. Set your own production application identifier and signing before store distribution.

## Implemented frontend

- FloraMW app name, leaf icon asset, branded startup and three introduction pages.
- First-run district and language setup. Searchable list of all 28 Malawi districts, grouped into Northern (6), Central (9) and Southern (13). District preference persists and is captured on saved discoveries. No GPS permission requested.
- Selectable English, Chichewa, Yao, Tumbuka, Sena, Lhomwe and Tonga. Resource-backed visible text, English fallback and an on-screen translation-status notice. **This is a localization framework, not seven completed translations.** Chichewa has draft navigation. Other requested packs are selectable but await native translations and review. Field hints, botanical prose and dynamic status text also require localization review.
- Discover with common/scientific/family search, clear action, category chips, A–Z/Z–A sorting and no-results/reset state.
- Camera/gallery consent explanation, system picker, selected-photo preview, removal, permission/access errors and Android lost-image recovery.
- Demo identification service with loading, cancellation, candidates, no-match, retry, and service-error states. Demo outcomes are independent of the photo and clearly labelled. No invented confidence scores.
- Plant profiles with save action, scientific name/family, local knowledge, medicinal research, Malawi occurrence, growing conditions, care, effects/precautions, legal/conservation and source/review sections.
- Persistent bookmarks, discovery history, app-private photo copies, district, editable journal notes and deletion.
- Correction form validation, optional reference, local draft saving, draft list and deletion. Nothing is submitted to a server.
- Settings for language, district, dark mode, larger text, replay introduction, privacy, help, about and deletion of all local records.
- Empty states, missing-photo fallback, accessible control tooltips, scrollable screens, system font scaling, offline bundled catalogue and storage-error messages.

## Important scope boundaries

AI inference, server APIs, authenticated accounts, cloud synchronization and feedback delivery are not connected. All catalogue records are sample data. No medical, traditional-use, local occurrence or legal claim is asserted as verified. Source/review fields are visible placeholders rather than fabricated evidence. Real content and complete native translations need qualified review before public release.

No network calls, location collection or analytics are implemented. SharedPreferences stores local structured state; app-private document storage holds saved photo copies. Operating-system backup behavior still applies. This is convenience storage for an educational frontend, not an encrypted health-record system.

## Validation completed here

- Dart formatter parsed and formatted all source and test files successfully.
- Nine local-only Dart checks passed: distinct district count, regional counts, requested language choices, English fallback, district/journal serialization, demo candidate labeling, no-match, service error, and complete profile section structure.
- Python checked the translation JSON, referenced source imports, icon asset, Python branding-script syntax, and archive integrity.

Flutter widget tests are included for persistence, welcome/district setup and no-match flow. **They were not executed.** Flutter analysis, native runner generation, compilation, emulator/device tests and APK/IPA builds remain unverified. Automatic approval review blocked Flutter's platform-generation command when the SDK attempted to contact a cloud metadata endpoint. No attempt was made to bypass that boundary. Generate runners and run the checks above in your own configured Flutter environment.

## Files

- `lib/main.dart`: app startup, themes, onboarding and discover shell.
- `lib/preferences.dart`: first-run setup and searchable district selector.
- `lib/locale_data.dart`: district identifiers and language labels.
- `lib/localization.dart`, `assets/translations.json`: translation lookup and English fallback.
- `lib/models.dart`: sample catalogue, journal models and identification interface/demo.
- `lib/store.dart`: local persistence, journal photos and record deletion.
- `lib/screens/`: identify, profile/corrections, garden/journal and settings/help/privacy.
- `tool/check_models.dart`: local-only executable model checks.
- `tool/brand_platforms.py`: native runner branding/configuration.
- `test/frontend_test.dart`: Flutter tests to run locally.
- `API_HANDOFF.md`: backend integration seam and verified-content requirements.
- `QA_CHECKLIST.md`: physical-device acceptance checks.

## Reference documentation

- Flutter: https://docs.flutter.dev/get-started
- Image picker setup: https://pub.dev/packages/image_picker
- Preferences: https://pub.dev/packages/shared_preferences
- App-private directories: https://pub.dev/packages/path_provider
- District list cross-check: https://gadm.org/maps/MWI_1.html
- Malawi local-government guidebook: https://www.resakss.org/sites/default/files/Malawi%20MLGRD%202013%20Guidebook%20on%20the%20Local%20Government%20System%20in%20Malawi.pdf

Use current official package documentation for platform minimums. Flutter dependency resolution selects compatible versions from pubspec constraints; a lockfile must be generated by `flutter pub get` before a reproducible release build.
