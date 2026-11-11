"""Internal machine learning botanical identification provider adapter.

Connects the internally trained botanical identification model developed by
Christopher C. N'goma, Prescott Magaleta, and Moses Munkhondya to the FloraMW
identification engine.

Satisfies the IdentificationProvider protocol, supporting:
  - 'mock' mode: Deterministic, contract-conforming inference simulation for testing and CI.
  - 'service' mode: Delegating inference to a separate containerized HTTP/gRPC model service.
  - 'artifact' mode: Direct in-process artifact execution (configured once runtime is selected).

Guarantees:
  - Framework independence (no hard PyTorch/ONNX/TensorFlow dependencies in this adapter).
  - Explicit configuration validation (no silent fallback to external providers).
  - Model and dataset metadata propagation for full auditability.
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

import httpx

from app.core.config import settings
from app.identification.exceptions import (
    ConfigurationError,
    ProviderNetworkError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.identification.provider import (
    IdentificationProvider,
    ImagePayload,
    ProviderCandidate,
    ProviderResult,
    normalise_scientific_name,
)

logger = logging.getLogger("floramw.identification.internal")


# Standard simulated species for mock/test mode
_MOCK_PREDICTIONS = [
    {
        "scientific_name": "Hibiscus rosa-sinensis",
        "confidence": 0.92,
        "common_names": ["Chinese hibiscus", "Rose mallow"],
        "family": "Malvaceae",
        "genus": "Hibiscus",
        "notes": "Simulated internal model inference result.",
    },
    {
        "scientific_name": "Catharanthus roseus",
        "confidence": 0.05,
        "common_names": ["Madagascar periwinkle"],
        "family": "Apocynaceae",
        "genus": "Catharanthus",
        "notes": "Simulated secondary candidate.",
    },
    {
        "scientific_name": "Delonix regia",
        "confidence": 0.02,
        "common_names": ["Flamboyant", "Royal poinciana"],
        "family": "Fabaceae",
        "genus": "Delonix",
        "notes": "Simulated tertiary candidate.",
    },
]


class InternalModelProvider(IdentificationProvider):
    """Adapter for the internally developed FloraMW machine learning model."""

    provider_id: str = "internal"

    def __init__(
        self,
        mode: Optional[str] = None,
        model_id: Optional[str] = None,
        model_version: Optional[str] = None,
        service_url: Optional[str] = None,
        timeout: Optional[float] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.mode = (mode or settings.INTERNAL_MODEL_MODE).lower().strip()
        self.model_id = model_id or settings.INTERNAL_MODEL_ID
        self.model_version = model_version or settings.INTERNAL_MODEL_VERSION
        self.service_url = (service_url or settings.INTERNAL_MODEL_SERVICE_URL).strip()
        self.timeout = timeout if timeout is not None else settings.INTERNAL_MODEL_TIMEOUT_SECONDS
        self._client = http_client

        self._validate_configuration()

    def _validate_configuration(self) -> None:
        """Validate configuration settings for the chosen operational mode."""
        if self.mode == "disabled":
            raise ProviderUnavailableError(
                "Internal botanical model is currently disabled in configuration."
            )

        if self.mode not in ("mock", "service", "artifact"):
            raise ConfigurationError(
                f"Unknown INTERNAL_MODEL_MODE '{self.mode}'. "
                "Must be 'mock', 'service', 'artifact', or 'disabled'."
            )

        if self.mode == "service" and not self.service_url:
            raise ConfigurationError(
                "INTERNAL_MODEL_MODE='service' requires a valid INTERNAL_MODEL_SERVICE_URL."
            )

        if self.mode == "artifact" and not settings.INTERNAL_MODEL_ARTIFACT_PATH:
            raise ConfigurationError(
                "INTERNAL_MODEL_MODE='artifact' requires a valid INTERNAL_MODEL_ARTIFACT_PATH."
            )

    async def identify(self, image: ImagePayload) -> ProviderResult:
        """Submit an image payload to the internal model and return candidates.

        Args:
            image: Validated ImagePayload.

        Returns:
            ProviderResult containing ranked candidates and model metadata.

        Raises:
            ProviderUnavailableError: If model service or artifact is inaccessible.
            ProviderTimeoutError: If inference exceeds timeout limit.
            ProviderResponseError: If inference response format is malformed.
        """
        start_time = time.perf_counter()

        if self.mode == "mock":
            return self._run_mock_inference(image, start_time)
        elif self.mode == "service":
            return await self._run_service_inference(image, start_time)
        elif self.mode == "artifact":
            return self._run_artifact_inference(image, start_time)
        else:
            raise ProviderUnavailableError(
                f"Unsupported operational mode for internal model: {self.mode}"
            )

    def _run_mock_inference(
        self, image: ImagePayload, start_time: float
    ) -> ProviderResult:
        """Return deterministic simulated predictions for testing and CI."""
        duration_ms = int((time.perf_counter() - start_time) * 1000)

        candidates = [
            ProviderCandidate(
                scientific_name=item["scientific_name"],
                confidence=item["confidence"],
                common_names=list(item["common_names"]),
                family=item["family"],
                genus=item["genus"],
                notes=item["notes"],
            )
            for item in _MOCK_PREDICTIONS
        ]

        logger.info(
            "Internal mock model inference executed: %d candidates returned in %d ms",
            len(candidates),
            duration_ms,
        )

        return ProviderResult(
            candidates=candidates,
            provider_id=self.provider_id,
            model_version=self.model_version,
            provider_meta={
                "model_id": self.model_id,
                "execution_mode": "mock",
                "execution_duration_ms": duration_ms,
                "image_width": image.width_px,
                "image_height": image.height_px,
            },
        )

    async def _run_service_inference(
        self, image: ImagePayload, start_time: float
    ) -> ProviderResult:
        """Call a hosted HTTP model inference service container."""
        files = {
            "image": (
                f"upload.{image.format.lower()}",
                image.content,
                f"image/{image.format.lower()}",
            )
        }

        client_provided = self._client is not None
        client = self._client or httpx.AsyncClient(timeout=self.timeout)

        try:
            response = await client.post(
                f"{self.service_url.rstrip('/')}/predict",
                files=files,
            )
        except httpx.TimeoutException as exc:
            logger.warning("Internal model service timed out: %s", exc)
            raise ProviderTimeoutError(
                f"Internal model inference timed out after {self.timeout}s"
            ) from None
        except httpx.NetworkError as exc:
            logger.error("Internal model service network error: %s", exc)
            raise ProviderNetworkError(
                "Unable to connect to internal model inference service"
            ) from None
        finally:
            if not client_provided:
                await client.aclose()

        if response.status_code != 200:
            raise ProviderResponseError(
                f"Internal model service returned error HTTP {response.status_code}"
            )

        try:
            data = response.json()
        except Exception as exc:
            raise ProviderResponseError(
                "Internal model service returned invalid JSON response"
            ) from exc

        return self._parse_service_response(data, start_time)

    def _parse_service_response(
        self, data: dict, start_time: float
    ) -> ProviderResult:
        """Parse and normalize JSON returned by a hosted inference service."""
        raw_candidates = data.get("candidates") or data.get("predictions") or []
        candidates: List[ProviderCandidate] = []

        for item in raw_candidates:
            if not isinstance(item, dict):
                continue

            sci_name = item.get("scientific_name") or item.get("label") or ""
            if not sci_name:
                continue

            try:
                confidence = float(item.get("confidence", 0.0))
            except (ValueError, TypeError):
                continue

            confidence = max(0.0, min(1.0, confidence))

            candidates.append(
                ProviderCandidate(
                    scientific_name=sci_name.strip(),
                    confidence=confidence,
                    common_names=item.get("common_names") or [],
                    family=item.get("family"),
                    genus=item.get("genus"),
                    provider_taxon_id=item.get("taxon_id"),
                    notes=item.get("notes"),
                )
            )

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        # Sort descending by confidence
        candidates.sort(key=lambda c: c.confidence, reverse=True)

        return ProviderResult(
            candidates=candidates,
            provider_id=self.provider_id,
            model_version=data.get("model_version") or self.model_version,
            provider_meta={
                "model_id": data.get("model_id") or self.model_id,
                "execution_mode": "service",
                "execution_duration_ms": duration_ms,
            },
        )

    def _run_artifact_inference(
        self, image: ImagePayload, start_time: float
    ) -> ProviderResult:
        """Execute in-process artifact inference once model runtime is selected."""
        raise ProviderUnavailableError(
            "Direct artifact execution requires the ML team to deliver the model artifact "
            "and confirm the runtime specification (e.g. ONNX Runtime / TorchScript)."
        )
