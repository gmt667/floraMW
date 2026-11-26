"""TensorFlow Lite adapter for the FloraMW MobileNetV2 flower classifier."""
from __future__ import annotations
import json
import logging
import time
from io import BytesIO
from pathlib import Path
from typing import Optional
import httpx
import numpy as np
from PIL import Image
from app.core.config import settings
from app.identification.exceptions import (
    ConfigurationError, MockProviderForbiddenError, ProviderNetworkError,
    ProviderResponseError, ProviderTimeoutError, ProviderUnavailableError,
)
from app.identification.provider import (
    IdentificationProvider, ImagePayload, ProviderCandidate, ProviderResult,
)

logger = logging.getLogger("floramw.identification.internal")
_MOCK = [ProviderCandidate("Hibiscus rosa-sinensis", 0.92,
    common_names=["Chinese hibiscus"], family="Malvaceae", genus="Hibiscus",
    notes="Simulated result; not a real model prediction.")]


class InternalModelProvider(IdentificationProvider):
    """Loads a local .tflite artifact and returns ranked scientific-name candidates."""
    provider_id = "floramw-internal-tflite"

    def __init__(self, mode: Optional[str] = None, model_id: Optional[str] = None,
                 model_version: Optional[str] = None, service_url: Optional[str] = None,
                 timeout: Optional[float] = None, http_client: Optional[httpx.AsyncClient] = None):
        self.mode = (mode or settings.INTERNAL_MODEL_MODE).lower().strip()
        self.model_id = model_id or settings.INTERNAL_MODEL_ID
        self.model_version = model_version or settings.INTERNAL_MODEL_VERSION
        self.service_url = (service_url or settings.INTERNAL_MODEL_SERVICE_URL).strip()
        self.timeout = timeout if timeout is not None else settings.INTERNAL_MODEL_TIMEOUT_SECONDS
        self._client = http_client
        self._interpreter = self._input = self._output = None
        self._labels: dict[int, str] = {}
        if self.mode == "disabled":
            raise ProviderUnavailableError("Internal flower model is disabled.")
        if self.mode == "mock" and (settings.ENVIRONMENT == "production" or not settings.ALLOW_MOCK_PROVIDER):
            raise MockProviderForbiddenError("Mock inference is forbidden in production or when disabled.")
        if self.mode not in ("mock", "service", "artifact"):
            raise ConfigurationError(f"Unknown INTERNAL_MODEL_MODE '{self.mode}'.")
        if self.mode == "service" and not self.service_url:
            raise ConfigurationError("INTERNAL_MODEL_SERVICE_URL is required for service mode.")
        if self.mode == "artifact":
            self._load_artifact()

    def _load_artifact(self) -> None:
        model = Path(settings.INTERNAL_MODEL_ARTIFACT_PATH).expanduser()
        labels = Path(settings.INTERNAL_MODEL_LABELS_PATH).expanduser()
        if not model.is_file() or model.suffix.lower() != ".tflite":
            raise ProviderUnavailableError(f"Missing or invalid TFLite artifact: {model}")
        if not labels.is_file():
            raise ProviderUnavailableError(f"Missing model labels JSON: {labels}")
        try:
            raw = json.loads(labels.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or not raw:
                raise ValueError("labels must be a non-empty JSON object")
            self._labels = {int(k): str(v).strip() for k, v in raw.items()}
            if sorted(self._labels) != list(range(len(self._labels))) or any(not v for v in self._labels.values()):
                raise ValueError("labels must have contiguous zero-based indexes and non-empty scientific names")
        except (OSError, ValueError, TypeError) as exc:
            raise ConfigurationError(f"Invalid labels JSON: {exc}") from exc
        try:
            try:
                from tflite_runtime.interpreter import Interpreter
            except ImportError:
                from tensorflow.lite import Interpreter
            self._interpreter = Interpreter(model_path=str(model), num_threads=2)
            self._interpreter.allocate_tensors()
            inputs, outputs = self._interpreter.get_input_details(), self._interpreter.get_output_details()
            if len(inputs) != 1 or not outputs:
                raise ValueError("Expected one input tensor and at least one output tensor.")
            shape = inputs[0]["shape"]
            if len(shape) != 4 or int(shape[-1]) != 3 or int(outputs[0]["shape"][-1]) != len(self._labels):
                raise ValueError(f"Tensor shape/label mismatch: input={shape}, output={outputs[0]['shape']}, labels={len(self._labels)}")
            self._input, self._output = inputs[0], outputs[0]
        except ImportError as exc:
            raise ProviderUnavailableError("Install the TFLite runtime (tflite-runtime) to run this model.") from exc
        except Exception as exc:
            raise ProviderUnavailableError(f"Unable to initialize TFLite model: {exc}") from exc

    async def identify(self, image: ImagePayload) -> ProviderResult:
        started = time.perf_counter()
        if self.mode == "mock":
            return ProviderResult(list(_MOCK), self.provider_id, self.model_version, {"execution_mode": "mock"})
        if self.mode == "artifact":
            return self._infer(image, started)
        return await self._infer_service(image, started)

    def _infer(self, image: ImagePayload, started: float) -> ProviderResult:
        try:
            with Image.open(BytesIO(image.content)) as src:
                pixels = np.asarray(src.convert("RGB").resize((224, 224), Image.Resampling.BILINEAR), dtype=np.float32)
            # Exact MobileNetV2 preprocessing used in ml/src/train.py.
            tensor = np.expand_dims(pixels / 127.5 - 1.0, axis=0)
            dtype = self._input["dtype"]
            if dtype != np.float32:
                scale, zero = self._input.get("quantization", (0.0, 0))
                if not scale:
                    raise ValueError("Quantized input tensor has no scale.")
                limits = np.iinfo(dtype)
                tensor = np.clip(np.round(tensor / scale + zero), limits.min, limits.max)
            self._interpreter.set_tensor(self._input["index"], tensor.astype(dtype))
            self._interpreter.invoke()
            scores = self._interpreter.get_tensor(self._output["index"])[0].astype(np.float32)
            if self._output["dtype"] != np.float32:
                scale, zero = self._output.get("quantization", (0.0, 0))
                if scale:
                    scores = (scores - zero) * scale
            if scores.ndim != 1 or len(scores) != len(self._labels) or not np.isfinite(scores).all():
                raise ValueError("Model returned invalid class scores.")
            if np.any(scores < 0) or np.any(scores > 1) or not np.isclose(scores.sum(), 1.0, atol=0.05):
                exp = np.exp(scores - scores.max())
                scores = exp / exp.sum()
            indexes = np.argsort(scores)[::-1][:3]
            candidates = [ProviderCandidate(self._labels[int(i)], float(scores[i]),
                provider_taxon_id=str(int(i)),
                notes="MobileNetV2 TFLite prototype; score is not calibrated accuracy.") for i in indexes]
        except Exception as exc:
            raise ProviderResponseError(f"TFLite inference failed: {exc}") from exc
        return ProviderResult(candidates, self.provider_id, self.model_version, {
            "model_id": self.model_id, "execution_mode": "artifact",
            "execution_duration_ms": int((time.perf_counter()-started)*1000), "class_count": len(self._labels)})

    async def _infer_service(self, image: ImagePayload, started: float) -> ProviderResult:
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        try:
            response = await client.post(f"{self.service_url.rstrip('/')}/predict",
                files={"image": (f"upload.{image.format.lower()}", image.content, f"image/{image.format.lower()}")})
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"Model service timed out after {self.timeout}s") from exc
        except httpx.NetworkError as exc:
            raise ProviderNetworkError("Unable to connect to internal model service") from exc
        except (httpx.HTTPStatusError, ValueError) as exc:
            raise ProviderResponseError(f"Invalid model service response: {exc}") from exc
        finally:
            if self._client is None:
                await client.aclose()
        candidates = []
        for item in data.get("candidates") or data.get("predictions") or []:
            if not isinstance(item, dict):
                continue
            name = item.get("scientific_name") or item.get("label")
            try:
                score = float(item.get("confidence", 0))
            except (ValueError, TypeError):
                continue
            if name and np.isfinite(score):
                candidates.append(ProviderCandidate(str(name).strip(), max(0.0, min(1.0, score))))
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return ProviderResult(candidates, self.provider_id, data.get("model_version") or self.model_version,
            {"model_id": data.get("model_id") or self.model_id, "execution_mode": "service",
             "execution_duration_ms": int((time.perf_counter()-started)*1000)})
