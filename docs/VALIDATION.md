# FloraMW validation

## Validation scope

GitHub Actions validates Flutter formatting, analysis, unit/widget tests, standalone model checks, asset/licence checks, an Android debug APK build and an unsigned iOS simulator build.

The live backend integration is separate from frontend CI. The live integration test in `test/live_integration_test.dart` targets a local development API at `http://127.0.0.1:8008` and skips when that service is not reachable. A passing frontend workflow does not prove that the production API host or identification provider is reachable.

## Backend integration implemented in the client

- Anonymous device-token registration and persistence.
- Server-managed flower catalogue and full profile retrieval, with bundled offline fallback.
- Multipart photo identification with explicit upload consent, provider/demo metadata and backend safety disclaimer.
- Offline-first field-journal metadata synchronization with durable outbox and preserved demo/live labels.
- Botanical correction report submission with local-draft fallback.

## Still requires deployment/device verification

- Supply `FLORAMW_API_BASE_URL` as a valid HTTPS origin when building release binaries.
- Verify production health, authentication, catalogue, full profile, photo identification, journal synchronization and report submission against the deployed API.
- Confirm a real identification provider and server-side key are configured; mock mode must be disabled in production.
- Confirm image retention/deletion terms with the provider and ensure they match the consent/privacy notice.
- Test camera/gallery permission flows, network loss/recovery, screen readers and representative physical devices.
- Complete translation, botanical, local-knowledge, clinical and legal review before public release.

The production API hostname and provider credentials are deployment configuration and are not embedded in the repository. No production readiness claim should be made until the deployed service passes the smoke tests in `API_HANDOFF.md`.
