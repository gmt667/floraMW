# FloraMW — ML Team Backend Integration Contract

**Version:** 1.0.0
**Issued:** 2026-11-11
**Issued By:** Backend Engineering (Principal Backend Architect)
**For:** Christopher C. N'goma, Prescott Magaleta, Moses Munkhondya

---

## 1. Purpose

This document defines the exact interface between the FloraMW FastAPI backend and the internally developed botanical identification model.

The backend is fully prepared and waiting. When your dataset, training pipeline, and model are ready, follow this contract to integrate your model without requiring any backend redesign.

---

## 2. What the Backend Provides

The backend gives your model:

1. **Validated image bytes** — Raw bytes have been fully sanitised, decoded and re-encoded by Pillow. You will never receive corrupted, truncated, or oversized images.
2. **A clean provider protocol** — Your model only needs to implement one async method.
3. **Automatic result persistence** — All identification events are automatically saved to the database with full provenance.
4. **Catalogue cross-referencing** — Your predictions are automatically matched against the botanical catalogue.
5. **API exposure** — Your results appear instantly in `POST /api/v1/identifications`.
6. **Idempotency** — Duplicate requests are automatically handled; your model is never called twice for the same image+request-id pair.
7. **Health and readiness monitoring** — Provider availability is checked at startup.

---

## 3. The Provider Protocol

Your model adapter must satisfy this Python Protocol:

```python
class IdentificationProvider(Protocol):
    provider_id: str  # Stable string, e.g. "floramw-internal-v1"

    async def identify(self, image: ImagePayload) -> ProviderResult:
        ...
```

Located at: `backend/app/identification/provider.py`

---

## 4. Identification Input: `ImagePayload`

Your model receives a fully validated `ImagePayload` dataclass:

```python
@dataclass(frozen=True)
class ImagePayload:
    content: bytes     # Raw image bytes (JPEG or PNG, Pillow-validated)
    format: str        # 'JPEG' or 'PNG' (canonical)
    width_px: int      # Image width in pixels
    height_px: int     # Image height in pixels
    size_bytes: int    # Byte length of content
```

**You must not read from the filesystem.** Only use `image.content`.

**Current backend limits:**
- Maximum upload size: 10 MB
- Maximum dimension: 4096 × 4096 px
- Formats: JPEG, PNG (WebP converted to JPEG before delivery)

---

## 5. Image Pre-processing — Your Responsibility

The backend provides clean, decoded image bytes. You are responsible for all model-specific pre-processing:

- Resizing to your model's required input dimensions (e.g. 224×224).
- Normalisation (e.g. ImageNet mean/std: `[0.485, 0.456, 0.406]`, `[0.229, 0.224, 0.225]`).
- Channel ordering (RGB vs BGR).
- Any augmentation or test-time transformations.

**You must supply `metadata.json` (see Section 11) specifying these values so the backend can validate that pre-processing is applied correctly.**

---

## 6. Required Output: `ProviderResult`

Your `identify()` method must return a `ProviderResult`:

```python
@dataclass
class ProviderResult:
    candidates: list[ProviderCandidate]  # Ordered highest-confidence first
    provider_id: str                     # Your stable provider ID
    model_version: str | None = None     # Your model version string
    provider_meta: dict[str, object] = field(default_factory=dict)
```

Each `ProviderCandidate`:

```python
@dataclass
class ProviderCandidate:
    scientific_name: str          # Full botanical binomial e.g. "Hibiscus rosa-sinensis"
    confidence: float             # Score in [0.0, 1.0]; MUST be finite
    common_names: list[str] = []  # Optional; leave empty if unknown
    family: str | None = None     # Botanical family e.g. "Malvaceae"
    genus: str | None = None      # Genus e.g. "Hibiscus"
    provider_taxon_id: str | None = None  # Your internal class index (optional)
    notes: str | None = None
```

---

## 7. Scientific Name and Class Label Mapping

**This is the most critical integration requirement.**

Your model predicts a class index (e.g. `42`). The backend needs the **botanical binomial scientific name** for that class.

You must provide `labels.json` mapping class indices to scientific names:

```json
{
  "0": "Faidherbia albida",
  "1": "Adansonia digitata",
  "2": "Hibiscus rosa-sinensis",
  "42": "Catharanthus roseus"
}
```

**Rules for scientific names:**
- Use the accepted full binomial (Genus + specific epithet).
- Do not include author abbreviations (e.g. write `"Hibiscus rosa-sinensis"`, not `"Hibiscus rosa-sinensis L."`).
- Do not use common names, local names, or codes as class labels.
- Use consistent capitalisation: first word capitalized, second word lowercase.

**Before training:** validate your class labels against the FloraMW catalogue using:

```bash
python -m app.core.taxonomy_check --labels path/to/labels.json
```

This reports how many of your class names already match the catalogue. Unmatched species can be added to the catalogue by a qualified botanist before launch.

---

## 8. Confidence Score Semantics

- Confidence must be a **finite float between 0.0 and 1.0** (inclusive).
- NaN and ±Infinity are rejected and the candidate is discarded.
- If your model outputs logits, apply softmax before returning.
- If your model outputs probabilities that do not sum to 1.0, the backend accepts them as-is.
- Candidates with confidence below `0.20` are classified as `"uncertain"`.
- The backend does **not** apply any additional calibration.

---

## 9. Error Handling — What Your Adapter Must Raise

Use the exception classes defined in `backend/app/identification/exceptions.py`:

| Situation | Exception to Raise |
|---|---|
| Model file not found or failed to load | `ProviderUnavailableError` |
| Inference service unreachable | `ProviderNetworkError` |
| Inference exceeded time limit | `ProviderTimeoutError` |
| Model returned malformed output | `ProviderResponseError` |
| Misconfiguration (missing API key, path, etc.) | `ConfigurationError` |

**Do not raise generic Python exceptions.** The backend translates these to appropriate HTTP status codes and safe error messages.

---

## 10. Timeout Expectations

The default inference timeout is **5 seconds** (`INTERNAL_MODEL_TIMEOUT_SECONDS`).

- Design your model to respond within this limit.
- If your model requires a longer warm-up period, raise `ProviderUnavailableError` while loading and implement a readiness probe.
- The timeout can be increased via the `.env` configuration if justified by your model architecture.

---

## 11. What You Must Deliver

Before the backend can integrate your model, you must provide:

### Required Files

| File | Description |
|---|---|
| `metadata.json` | Model provenance, preprocessing specification, and input dimensions |
| `labels.json` | Class index → scientific name mapping |
| Model artifact OR service endpoint URL | Depends on deployment mode (see Section 12) |

### `metadata.json` Template

```json
{
  "model_id": "floramw-mobilenet-v1",
  "version": "1.0.0",
  "description": "MobileNetV3 trained on FloraMW Malawi flower dataset",
  "target_size": [224, 224],
  "normalization_mean": [0.485, 0.456, 0.406],
  "normalization_std": [0.229, 0.224, 0.225],
  "channel_order": "RGB",
  "dataset_version": "floramw-ds-2026.1",
  "species_count": 42,
  "training_accuracy_top1": 0.87,
  "training_accuracy_top5": 0.96,
  "framework": "onnx",
  "artifact_filename": "floramw_model_v1.onnx"
}
```

### `labels.json` Template

```json
{
  "0": "Faidherbia albida",
  "1": "Adansonia digitata",
  "2": "Hibiscus rosa-sinensis"
}
```

---

## 12. Deployment Mode — Confirm Before Integration

The backend supports two integration modes. **You must confirm which mode your team will use:**

### Mode A: Local Artifact (In-Process Inference)

- You export the trained model as an artifact (recommended: `.onnx` for framework independence).
- The backend loads the artifact at startup.
- Configuration: `INTERNAL_MODEL_MODE=artifact`, `INTERNAL_MODEL_ARTIFACT_PATH=/path/to/model.onnx`.
- **Advantage:** No network dependency; suitable for single-server deployment.
- **Requires:** The backend team to add the appropriate runtime library (e.g. `onnxruntime`).

### Mode B: Hosted Inference Service

- You run the model in a separate container (e.g. TorchServe, Triton, or a lightweight Flask/FastAPI service).
- The backend proxies image bytes to `POST {service_url}/predict` and receives JSON candidates.
- Configuration: `INTERNAL_MODEL_MODE=service`, `INTERNAL_MODEL_SERVICE_URL=http://inference:8080`.
- **Advantage:** Decoupled deployment; model can be updated without restarting the backend.
- **Requires:** Your service to accept multipart image uploads and return JSON in the expected format.

#### Expected Service Response Format

```json
{
  "model_id": "floramw-mobilenet-v1",
  "model_version": "1.0.0",
  "candidates": [
    {
      "scientific_name": "Hibiscus rosa-sinensis",
      "confidence": 0.92,
      "common_names": ["Chinese hibiscus"],
      "family": "Malvaceae",
      "genus": "Hibiscus",
      "taxon_id": "2"
    }
  ]
}
```

---

## 13. Provider Identifier and Versioning

Set your `provider_id` to a stable string:
- Recommended: `"floramw-internal-v1"` (increment on major architecture changes).
- Always return `model_version` matching the version in `metadata.json`.

The backend stores these in the database with every identification request for full auditability.

---

## 14. Testing Requirements

Before requesting backend integration, run:

1. **Taxonomic validation:**
   ```bash
   python -m app.core.taxonomy_check --labels labels.json
   ```
   All expected species should be matched.

2. **Mock provider test (CI):**
   The backend has a fully working mock internal provider (`InternalModelProvider` in mock mode). Your integration replaces it. All existing 152+ tests must continue to pass after integration.

3. **End-to-end test:**
   Submit a real botanical photograph to `POST /api/v1/identifications` with your adapter configured.

4. **No-match test:**
   Submit a non-plant image. Your model must return `candidates=[]` (empty list), not an error.

5. **Timeout test:**
   Verify that your model responds within `INTERNAL_MODEL_TIMEOUT_SECONDS`. The backend raises `ProviderTimeoutError` if it does not.

---

## 15. Configuration Variables

Add these to `backend/.env` for your integration:

```env
IDENTIFICATION_PROVIDER=internal
INTERNAL_MODEL_MODE=artifact        # or 'service' or 'mock'
INTERNAL_MODEL_ID=floramw-mobilenet-v1
INTERNAL_MODEL_VERSION=1.0.0
INTERNAL_MODEL_ARTIFACT_PATH=/path/to/floramw_model_v1.onnx
INTERNAL_MODEL_SERVICE_URL=http://inference-service:8080  # only for mode=service
INTERNAL_MODEL_TIMEOUT_SECONDS=5.0
INTERNAL_MODEL_LABELS_PATH=/path/to/labels.json
```

---

## 16. What the Backend Will NOT Do

To avoid confusion about responsibilities:

- The backend will **not** collect training data.
- The backend will **not** run preprocessing, augmentation, or data pipelines.
- The backend will **not** train or fine-tune your model.
- The backend will **not** evaluate model accuracy or recommend architectural changes.
- The backend will **not** automatically add unverified ML predictions to the botanical catalogue.
- The backend will **not** assume a specific ML framework until you confirm it.

---

## 17. Contact and Next Steps

When your model is ready:

1. Submit `metadata.json` and `labels.json` to the backend team.
2. Confirm deployment mode (A or B from Section 12).
3. The backend team will implement the runtime adapter and register the provider.
4. Run the test suite together.
5. Conduct a live end-to-end identification test with a real Malawi botanical photograph.

> **Note:** The `InternalModelProvider` in `backend/app/identification/internal_provider.py` is already registered and working in `mock` mode. It demonstrates exactly what your adapter must replace. Read that file as your implementation reference.
