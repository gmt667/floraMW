"""Pl@ntNet botanical identification provider adapter for FloraMW.

Integrates with the official Pl@ntNet identification API (v2):
- Official API docs: https://my.plantnet.org/doc/api/identify
- Portal & API keys: https://my.plantnet.org/

Conforms to the IdentificationProvider protocol:
- Submits multipart image payload to POST /v2/identify/{project}
- Authenticates via server-side API key passed in request parameters
- Maps Pl@ntNet species and score candidates into ProviderCandidate models
- Never exposes API keys in logs, exceptions, or provider metadata
- Handles network errors, timeouts, rate limits (429), auth failures (401/403),
  and upstream failures (5xx) with mapped FloraMW exceptions
- Treats Pl@ntNet 404 ('Species not found') as a valid no-match result
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import math
from typing import Any

import httpx
from PIL import Image

from app.core.config import settings
from app.identification.exceptions import (
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.identification.provider import (
    ImagePayload,
    ProviderCandidate,
    ProviderResult,
)

logger = logging.getLogger("floramw.identification.plantnet")

PROVIDER_ID = "plantnet"


def _sanitize_message(message: str, api_key: str | None) -> str:
    """Mask any occurrence of the API key in log or exception messages."""
    if not api_key or not api_key.strip():
        return message
    return message.replace(api_key, "***")


class PlantNetProvider:
    """Pl@ntNet v2 identification API provider adapter."""

    provider_id: str = PROVIDER_ID

    def __init__(
        self,
        api_key: str | None = None,
        project: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        connect_timeout: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.PLANTNET_API_KEY
        self.project = project or settings.PLANTNET_PROJECT
        self.base_url = (base_url or settings.PLANTNET_API_BASE_URL).rstrip("/")
        self.timeout = timeout or settings.PLANTNET_TIMEOUT_SECONDS
        self.connect_timeout = (
            connect_timeout or settings.PLANTNET_CONNECT_TIMEOUT_SECONDS
        )
        self._custom_client = http_client

    def _ensure_jpeg_or_png(self, image: ImagePayload) -> tuple[bytes, str, str]:
        """Ensure image content is JPEG or PNG for Pl@ntNet ingestion.

        Returns (bytes, filename, content_type).
        """
        fmt = (image.format or "").upper()
        if fmt == "PNG":
            return image.content, "image.png", "image/png"
        elif fmt == "JPEG" or fmt == "JPG":
            return image.content, "image.jpg", "image/jpeg"

        # Defensive fallback: convert in-memory to JPEG if unexpected format
        logger.warning(
            "Converting unexpected image format '%s' to JPEG for Pl@ntNet submission.",
            image.format,
        )
        try:
            with Image.open(io.BytesIO(image.content)) as pil_img:
                if pil_img.mode not in ("RGB", "L"):
                    pil_img = pil_img.convert("RGB")
                buf = io.BytesIO()
                pil_img.save(buf, format="JPEG", quality=85, optimize=True)
                return buf.getvalue(), "image.jpg", "image/jpeg"
        except Exception as exc:
            logger.error("Failed to convert image to JPEG: %s", exc)
            raise ProviderResponseError(
                "Failed to prepare image for identification provider."
            ) from exc

    def _parse_candidate(self, item: dict[str, Any]) -> ProviderCandidate | None:
        """Parse a single result entry from Pl@ntNet JSON response."""
        score_raw = item.get("score")
        if score_raw is None:
            return None
        try:
            score = float(score_raw)
        except (ValueError, TypeError):
            return None

        if not math.isfinite(score) or not (0.0 <= score <= 1.0):
            return None

        species = item.get("species")
        if not isinstance(species, dict):
            return None

        # Prefer scientificNameWithoutAuthor for direct binomial catalogue lookup
        scientific_name = (
            species.get("scientificNameWithoutAuthor")
            or species.get("scientificName")
            or ""
        ).strip()

        if not scientific_name:
            return None

        # Common names list
        common_names_raw = species.get("commonNames")
        common_names: list[str] = []
        if isinstance(common_names_raw, list):
            common_names = [
                str(name).strip()
                for name in common_names_raw
                if isinstance(name, (str, int)) and str(name).strip()
            ]

        # Extract taxonomic hierarchy
        family_obj = species.get("family")
        family = None
        if isinstance(family_obj, dict):
            family = (
                family_obj.get("scientificNameWithoutAuthor")
                or family_obj.get("scientificName")
            )
        elif isinstance(family_obj, str) and family_obj.strip():
            family = family_obj.strip()

        genus_obj = species.get("genus")
        genus = None
        if isinstance(genus_obj, dict):
            genus = (
                genus_obj.get("scientificNameWithoutAuthor")
                or genus_obj.get("scientificName")
            )
        elif isinstance(genus_obj, str) and genus_obj.strip():
            genus = genus_obj.strip()

        # Authorship for documentation notes
        authorship = species.get("scientificNameAuthorship")
        notes = f"Pl@ntNet match (authorship: {authorship})" if authorship else None

        taxon_id = None
        if "id" in species:
            taxon_id = f"plantnet:{species['id']}"
        else:
            taxon_id = f"plantnet:{scientific_name}"

        return ProviderCandidate(
            scientific_name=scientific_name,
            confidence=score,
            common_names=common_names,
            family=family,
            genus=genus,
            provider_taxon_id=taxon_id,
            notes=notes,
        )

    async def _send_request(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, Any],
        files: dict[str, Any],
        data: dict[str, Any],
    ) -> httpx.Response:
        """Send the identification request with bounded retry on network hiccups."""
        # Max 2 attempts total (1 retry for transient connect failure or 503)
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            try:
                response = await client.post(
                    url,
                    params=params,
                    files=files,
                    data=data,
                )
                # If 503/502 and have attempts left, retry once with backoff
                if response.status_code in (502, 503) and attempt < max_attempts:
                    logger.warning(
                        "Pl@ntNet returned %d on attempt %d; retrying once after backoff...",
                        response.status_code,
                        attempt,
                    )
                    await asyncio.sleep(0.5)
                    continue
                return response
            except (httpx.ConnectError, httpx.NetworkError) as exc:
                sanitized_msg = _sanitize_message(str(exc), self.api_key)
                if attempt < max_attempts:
                    logger.warning(
                        "Pl@ntNet connection failed on attempt %d: %s; retrying once...",
                        attempt,
                        sanitized_msg,
                    )
                    await asyncio.sleep(0.5)
                    continue
                logger.error("Pl@ntNet connection failed: %s", sanitized_msg)
                raise ProviderUnavailableError(
                    "Unable to connect to Pl@ntNet botanical identification API."
                ) from None
            except httpx.TimeoutException as exc:
                sanitized_msg = _sanitize_message(str(exc), self.api_key)
                logger.warning(
                    "Pl@ntNet timeout on attempt %d: %s",
                    attempt,
                    sanitized_msg,
                )
                raise ProviderTimeoutError(
                    "Pl@ntNet botanical identification API request timed out."
                ) from None

        raise ProviderUnavailableError("Pl@ntNet request failed after retries.")

    async def identify(self, image: ImagePayload) -> ProviderResult:
        """Submit image to Pl@ntNet API and return normalized candidates.

        Raises:
            ProviderUnavailableError: Missing API key, connection failed, auth error (401/403),
                                     or rate limit exceeded (429).
            ProviderTimeoutError:     Network or read timeout.
            ProviderResponseError:    Malformed JSON or unrecoverable API error.
        """
        # 1. API key guard
        api_key = (self.api_key or "").strip()
        if not api_key:
            raise ProviderUnavailableError(
                "Pl@ntNet API key is not configured. Set PLANTNET_API_KEY in backend/.env."
            )

        # 2. Image preparation
        content_bytes, filename, content_type = self._ensure_jpeg_or_png(image)

        # 3. URL and parameter construction
        project = (self.project or "all").strip()
        url = f"{self.base_url}/{project}"
        params = {
            "api-key": api_key,
            "lang": settings.PLANTNET_LANGUAGE,
            "include-related-images": "false",
            "nb-results": str(settings.PLANTNET_MAX_RESULTS),
        }

        # Safe logging without leaking API key
        logger.info(
            "Submitting image to Pl@ntNet [project=%s, url=%s?api-key=***, size=%d bytes, format=%s]",
            project,
            url,
            len(content_bytes),
            image.format,
        )

        files = {
            "images": (filename, content_bytes, content_type),
        }
        data = {
            "organs": settings.PLANTNET_DEFAULT_ORGAN,
        }

        # 4. HTTP transmission
        timeouts = httpx.Timeout(
            timeout=self.timeout,
            connect=self.connect_timeout,
        )

        if self._custom_client:
            response = await self._send_request(
                self._custom_client, url, params, files, data
            )
        else:
            async with httpx.AsyncClient(timeout=timeouts) as client:
                response = await self._send_request(
                    client, url, params, files, data
                )

        # 5. Status code handling
        status_code = response.status_code

        # Auth failures (401 / 403)
        if status_code in (401, 403):
            logger.error("Pl@ntNet authentication failed with HTTP %d", status_code)
            raise ProviderUnavailableError(
                "Pl@ntNet authentication failed. Please verify the configured API key."
            )

        # Rate limiting (429)
        if status_code == 429:
            logger.warning("Pl@ntNet rate limit exceeded (HTTP 429)")
            raise ProviderUnavailableError(
                "Pl@ntNet rate limit exceeded. Please retry after some time."
            )

        # Upstream errors (5xx)
        if 500 <= status_code <= 599:
            logger.error("Pl@ntNet upstream error HTTP %d", status_code)
            raise ProviderUnavailableError(
                f"Pl@ntNet service experienced an upstream error (HTTP {status_code})."
            )

        # 404 can indicate either 'Species not found' (valid no-match) or invalid project
        if status_code == 404:
            try:
                body_404 = response.json()
                msg = str(body_404.get("message", "")).lower()
                if "project" in msg:
                    raise ProviderResponseError(
                        f"Pl@ntNet project or referential not found: {project}"
                    )
                if "species" in msg or "not found" in msg or "no result" in msg:
                    logger.info("Pl@ntNet returned 404 (%s) -> valid NO_MATCH", msg)
                    return ProviderResult(
                        candidates=[],
                        provider_id=PROVIDER_ID,
                        model_version=body_404.get("version"),
                        provider_meta={"project": project, "outcome": "no_match"},
                    )
            except ProviderResponseError:
                raise
            except Exception:
                pass
            raise ProviderResponseError(
                f"Pl@ntNet project or resource not found: {project}"
            )

        # Other client errors (400, etc.)
        if 400 <= status_code < 500:
            sanitized_body = _sanitize_message(response.text[:200], self.api_key)
            logger.error(
                "Pl@ntNet rejected request with HTTP %d: %s",
                status_code,
                sanitized_body,
            )
            raise ProviderResponseError(
                f"Pl@ntNet rejected the identification request (HTTP {status_code})."
            )

        # 6. Response parsing
        try:
            body = response.json()
        except (json.JSONDecodeError, Exception) as exc:
            logger.error("Failed to decode Pl@ntNet response as JSON: %s", exc)
            raise ProviderResponseError(
                "Pl@ntNet returned an invalid or unparseable JSON response."
            ) from exc

        if not isinstance(body, dict):
            raise ProviderResponseError(
                "Pl@ntNet response body is not a JSON object."
            )

        raw_results = body.get("results")
        if not raw_results or not isinstance(raw_results, list):
            logger.info("Pl@ntNet returned empty results list -> NO_MATCH")
            return ProviderResult(
                candidates=[],
                provider_id=PROVIDER_ID,
                model_version=body.get("version"),
                provider_meta={
                    "project": project,
                    "preferedReferential": body.get("preferedReferential"),
                },
            )

        # 7. Candidate mapping
        candidates: list[ProviderCandidate] = []
        for item in raw_results:
            if isinstance(item, dict):
                cand = self._parse_candidate(item)
                if cand is not None:
                    candidates.append(cand)

        # Sort by confidence descending
        candidates.sort(key=lambda c: c.confidence, reverse=True)

        logger.info(
            "Pl@ntNet identification succeeded: %d candidates returned",
            len(candidates),
        )

        return ProviderResult(
            candidates=candidates,
            provider_id=PROVIDER_ID,
            model_version=body.get("version"),
            provider_meta={
                "project": project,
                "preferedReferential": body.get("preferedReferential"),
                "bestMatch": body.get("bestMatch"),
            },
        )
