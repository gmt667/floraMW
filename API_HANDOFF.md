# Backend handoff

The app currently injects `DemoIdentificationService` into `IdentifyScreen`.
Implement `IdentificationService` to replace this seam. Never put provider secrets in the mobile bundle.

## Required production changes
- Add a specific photo upload consent step with retention/deletion information before enabling network requests.
- POST an image with bounded size and timeout to the application's backend, not directly to a secret-key model provider.
- Return typed states for candidates, unknown/no-match, network unavailable, timeout, rate limit and server failure.
- Add calibrated evidence/uncertainty from the service rather than invented percentages. Do not present a candidate as a confirmed species.
- Add cancellation at transport level. Current generation tokens ignore late demo results.
- Load plant records using stable IDs; do not silently use the sample catalogue as a real result database.
- Add authenticated feedback submission if required. Drafts currently have status `local-draft` and are never sent.

## Suggested identification response
```json
{
  "request_id": "server-generated-id",
  "model_version": "provider-model-version",
  "status": "candidates",
  "is_demo": false,
  "candidates": [
    {"plant_id": "verified-species-id", "uncertainty_label": "possible match", "distinguishing_features": []}
  ],
  "warnings": ["Confirm identity with a qualified botanist before use."]
}
```
No-match returns an empty candidates array and status `unknown`. Frontend demonstration results have `isDemo: true` and journal records are visually labelled DEMO.

## Reviewed profile fields
Common/scientific/local names; family; reference photographs and licences; diagnostic features and lookalikes; Malawi distribution and source; native/introduced/conservation status; habitat and altitude; soil, rainfall and sun; flowering season; care, propagation, pests and management; research compounds, plant parts and evidence stage; approved medicine links where verified; community-attributed beliefs with consent; adverse effects and interactions; legal jurisdiction, authority links and review date; reviewer identity; source bibliography.

Do not publish clinical, cultural, distribution or legal placeholders as verified records. Complete native translations and community review for Chichewa, Yao, Tumbuka, Sena, Lhomwe and Tonga before calling the app fully multilingual. District preference is user-selected, not GPS-derived or botanical-distribution evidence.
