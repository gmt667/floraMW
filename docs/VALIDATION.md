# Frontend validation — 8 November 2026

Validated implementation commit: `8fbd3b7bfffdd6810674d1a855c637b6b024dbed`.

## Passed

- Flutter 3.47.9 analysis: no issues, locally and in GitHub CI.
- All **14** tests passed locally and in CI: eleven widget/state/layout/accessibility tests and three screenshot-comparison tests.
- Coverage includes all 28 districts, seven language choices, preference migration, persistent records and local translations, onboarding, no-match flow, narrow screens, large text, source sections, labelled controls and Android tap-target guidelines.
- Standalone model checks and asset/licence/native-metadata checks passed.
- Native Android and iOS runners generated with app branding and permission descriptions.
- **Android debug APK compiled successfully**, locally and in CI. Local APK signature verification passed. Manifest confirms FloraMW, package `mw.floramw.floramw`, minimum Android API 24 and target API 36. Bundled font licence and image-credit assets were verified in the APK.
- **Unsigned iOS simulator build compiled successfully** in GitHub CI on macOS. This is compilation validation, not physical iPhone testing or production signing.
- Discover, Identify and Plant profile screenshots were rendered from Flutter widgets and visually inspected. They are not physical-device screenshots.

## Download the Android demonstration

[Successful frontend workflow run](https://github.com/gmt667/floraMW/actions/runs/42473007899)

Open its **Artifacts** section and download **FloraMW-Android-demo**, then extract `app-debug.apk`. The artifact is a development-signed demonstration, not a store release. GitHub reports expiry on 6 February 2027; the repository retains the source and reproducible build instructions after artifact expiry.

Local build SHA-256 (the CI build can differ because it uses a separate development signing key):

`ba71b5ad96c305e94bd4aa8bf1ad42f74cb97187515786db028051cb8bcbbc9a`

## Still requires devices or qualified review

- Physical Android/iOS camera/gallery selection, permission refusal/revocation and OS lifecycle recovery.
- Screen-reader traversal, external source links, representative device font scaling and performance.
- Production Android/iOS signing and any store publication. No production signing key is included.
- Complete native translations, community-attributed local knowledge and qualified botanical, clinical and legal review. Source-linked general profiles do not establish Malawi district occurrence.
- Live identification/backend behavior. **No backend, server endpoint, live AI connection or cloud submission service was added or changed.**

The app labels demonstration candidates independently of the selected photo. Missing translations fall back to English visibly; language selection does not claim that a pack has been fully translated or approved.
