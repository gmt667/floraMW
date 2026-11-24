# FloraMW backend integration handoff

## Current integration status

The Flutter application is integrated with the FastAPI backend through `lib/services/api_client.dart`.

| Feature | Mobile integration | Backend contract |
|---|---|---|
| Flower catalogue | Fetches paginated catalogue; falls back to bundled reference data when offline | `GET /api/v1/flowers` |
| Flower profile | Fetches full server-managed sections and source references; uses bundled data if unavailable | `GET /api/v1/flowers/{flower_id}` |
| Anonymous device identity | Creates and persists a bearer token; refreshes once after HTTP 401 | `POST /api/v1/auth/anonymous` |
| Photo identification | Requires explicit photo-upload consent; uploads multipart field `image` | `POST /api/v1/identifications` |
| Field journal | Local-first durable outbox synchronizes create/update/delete operations | `/api/v1/flowers/observations` |
| Botanical corrections | Submits reports; if the request fails, keeps a local draft | `POST /api/v1/flowers/reports` |

The selected identification photo is copied to the device's app-private storage for the journal. The current journal sync sends the flower ID, timestamp, district, note and demo flag; it does not upload journal photo files.

## Configure the API origin

The API origin is supplied at build time. It must be the origin only, without the `/api/v1` suffix.

```sh
flutter run --dart-define=FLORAMW_API_BASE_URL=https://your-api-host
flutter build apk --release --dart-define=FLORAMW_API_BASE_URL=https://your-api-host
```

Release builds reject a missing or non-HTTPS API URL. Development builds use emulator/localhost defaults when the define is omitted. Do not put provider credentials or secrets in the Flutter app.

## Identification provider requirements

- Configure the backend with the intended provider and its server-side API key.
- In production, set `ENVIRONMENT=production`, `IDENTIFICATION_PROVIDER=plantnet` (or the approved provider), and `ALLOW_MOCK_PROVIDER=false`.
- Never expose provider keys in `--dart-define`, app assets, source control or client logs.
- The app displays the provider ID, demo status and backend safety disclaimer.
- Responses from a mock/deterministic provider are labelled as demonstration candidates; they must not be presented as photo predictions.
- A live candidate is still a possible match, not a botanist-confirmed identification.

## Image handling and consent

Before identification, the app explains that the selected photo is uploaded to the FloraMW backend and forwarded to the configured provider. Backend/provider retention is governed by the deployed service and provider policies. Publish a clear retention/deletion policy before production release; the mobile consent text must match that policy.

The identification endpoint validates image content, dimensions and size. Keep the backend upload limit aligned with the mobile image-picker settings. The backend should not log raw image bytes or persist photos unless a separately reviewed feature is introduced.

## Offline and ownership behavior

- Catalogue and profile content fall back to bundled reference content when the API cannot be reached.
- Journal records are saved locally first and synchronized through a durable FIFO outbox.
- Device tokens are stored locally and are not shared between devices.
- A fresh install creates a new anonymous identity; server history is not automatically migrated to it.
- Bookmarks and the selected language/theme remain local.
- Reports that cannot be submitted remain marked as local drafts and can be reviewed from the app's drafts area.

## Deployment checklist

1. Set `FLORAMW_API_BASE_URL` to the production HTTPS origin at build time.
2. Configure production database, migrations, Redis/rate limiting and explicit CORS origins as required by the backend deployment.
3. Set the real identification provider and server-side API key; disable mock providers in production.
4. Verify `GET /health`, `POST /api/v1/auth/anonymous`, `GET /api/v1/flowers`, `GET /api/v1/flowers/hibiscus`, photo identification, observation create/update/delete and report submission against the deployed host.
5. Confirm that the provider's image retention policy and the app's consent/privacy text agree.
6. Run Flutter analysis/tests and backend tests before release.

## Remaining operational work

A code-level integration does not prove that a particular hosted backend is reachable. The production API hostname and provider credentials are deployment configuration and must be supplied by the deployment owner. The live integration test in `test/live_integration_test.dart` targets a local development backend; it is not a substitute for production smoke testing.
