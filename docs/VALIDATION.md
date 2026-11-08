# Frontend validation — 8 November 2026

## Completed locally

- Flutter SDK 3.47.9 / Linux.
- Android and iOS native runner generation succeeded with explicit CI mode, avoiding the SDK's automatic cloud metadata detection request.
- Flutter analyzer: no issues.
- Eleven widget/state/layout/accessibility tests passed, covering all 28 districts, language choices, persistence, onboarding/district setup, no-match flow, narrow-screen navigation, large text, source sections and local translation edits and language-code migration.
- Three additional screenshot-comparison tests passed; Flutter-rendered references were generated and visually inspected: Discover, Identify and Plant profile. These are not screenshots from a physical phone.
- Standalone Dart model checks and Python asset/licence/native-metadata checks are included for repeatable local/CI validation.

## Pending results

Android APK compilation is being checked separately. The source includes CI build jobs, but the presence of a workflow file is not proof that a hosted run succeeded. Update this record only after observing actual results.

## Requires real devices or external review

- Physical Android/iOS camera/gallery selection, permission refusal/revocation and OS lifecycle recovery.
- Screen reader traversal, external source links, actual device font scaling and representative low-end device performance.
- iOS Xcode compilation/signing on macOS and any store submission.
- Full native translations and qualified review of botanical, clinical, cultural and legal information.
- Live identification/backend behavior. No backend was added or changed.

Sample candidates remain demo output, not a prediction from the selected photo. General reference content has source links; local traditional claims and Malawi occurrence remain explicitly unverified.
