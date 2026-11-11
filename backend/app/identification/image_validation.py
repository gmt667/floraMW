"""Image validation and preparation layer for FloraMW identification.

Responsibilities:
- Read and size-check the raw upload bytes.
- Detect the actual image format from content (not filename extension).
- Validate that MIME type and content format are consistent.
- Decode and re-encode the image to strip EXIF metadata (including GPS).
- Apply EXIF orientation correction before stripping metadata.
- Enforce pixel dimension limits.
- Return a clean ImagePayload ready for the provider.

Security notes:
- File content is never written to the local filesystem.
- Path traversal is impossible: we work only with in-memory bytes.
- EXIF stripping removes GPS coordinates and personal device metadata.
- Pillow's DecompressionBombWarning threshold is respected; oversized
  decompressed images raise DecompressionBombError before pixel reading.
- Output format is always JPEG or PNG; no other format leaves this layer.
"""

from __future__ import annotations

import io
import logging

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings
from app.identification.exceptions import (
    EmptyUploadError,
    FileTooLargeError,
    ImageDecodingError,
    ImageDimensionError,
    ImageValidationError,
    UnsupportedFormatError,
)
from app.identification.provider import ImagePayload

logger = logging.getLogger("floramw.identification.image")

# Formats we accept from the upload and can safely process
_SUPPORTED_FORMATS: frozenset[str] = frozenset({"JPEG", "PNG", "WEBP"})

# Formats we output (WEBP is converted to JPEG for consistency)
_OUTPUT_FORMAT_MAP: dict[str, str] = {
    "JPEG": "JPEG",
    "PNG": "PNG",
    "WEBP": "JPEG",
}

# MIME types accepted in multipart uploads (checked against declared content-type)
SUPPORTED_MIME_TYPES: frozenset[str] = frozenset({
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
})

# Map declared MIME types to expected Pillow format strings
_MIME_TO_FORMAT: dict[str, str] = {
    "image/jpeg": "JPEG",
    "image/jpg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}


def validate_and_prepare(
    raw_bytes: bytes,
    declared_content_type: str | None = None,
) -> ImagePayload:
    """Validate raw image bytes and return a clean, stripped ImagePayload.

    Args:
        raw_bytes:             Raw bytes from the multipart upload.
        declared_content_type: Content-Type header value from the upload
                               (e.g. 'image/jpeg'). Used for consistency
                               checking; actual format is determined from
                               file content.

    Returns:
        ImagePayload with validated content, correct orientation, and no EXIF.

    Raises:
        EmptyUploadError:       Zero-byte upload.
        FileTooLargeError:      File exceeds MAX_UPLOAD_SIZE_BYTES.
        UnsupportedFormatError: Format not in supported set, or format/MIME
                                mismatch.
        ImageDecodingError:     Pillow cannot decode the file (truncated,
                                corrupted, or not an image).
        ImageDimensionError:    Pixel dimensions exceed MAX_IMAGE_DIMENSION_PX.
    """
    # 1. Empty upload guard
    if not raw_bytes:
        raise EmptyUploadError("Uploaded file is empty. Please select a photograph.")

    # 2. Size guard (before decoding — prevents unbounded memory use)
    max_bytes = settings.MAX_UPLOAD_SIZE_BYTES
    if len(raw_bytes) > max_bytes:
        raise FileTooLargeError(len(raw_bytes), max_bytes)

    # 3. Decode and detect actual format
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img.verify()  # Catch truncated images early
    except (UnidentifiedImageError, Exception) as exc:
        logger.debug("Image decode failed: %s", exc)
        raise ImageDecodingError(
            "The uploaded file could not be read as an image. "
            "It may be corrupted, truncated, or not a valid photograph."
        ) from exc

    # Re-open after verify() (verify() leaves the file pointer in an unknown state)
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        actual_format: str | None = img.format
    except Exception as exc:
        raise ImageDecodingError(
            "The uploaded file could not be opened after verification."
        ) from exc

    # 4. Format allow-list
    if actual_format not in _SUPPORTED_FORMATS:
        raise UnsupportedFormatError(actual_format)

    # 5. MIME/content consistency check
    if declared_content_type:
        normalised_mime = declared_content_type.split(";")[0].strip().lower()
        expected_format = _MIME_TO_FORMAT.get(normalised_mime)
        if expected_format is not None and expected_format != actual_format:
            # Allow image/jpg and image/jpeg to both map to JPEG without raising
            if not (expected_format == "JPEG" and actual_format == "JPEG"):
                raise UnsupportedFormatError(actual_format)

    # 6. Dimension guard (checked BEFORE decompression or conversion to prevent memory exhaustion)
    max_dim = settings.MAX_IMAGE_DIMENSION_PX
    width, height = img.size
    if width > max_dim or height > max_dim:
        raise ImageDimensionError(width, height, max_dim)

    # 7. Apply EXIF orientation correction (before stripping metadata)
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        # Non-fatal: if EXIF orientation cannot be applied, proceed with original
        pass

    # Re-check dimensions in case transposition swapped/adjusted them
    width, height = img.size
    if width > max_dim or height > max_dim:
        raise ImageDimensionError(width, height, max_dim)

    # 8. Convert to RGB or RGBA as appropriate (strips palette modes, CMYK, etc.)
    output_format = _OUTPUT_FORMAT_MAP[actual_format]
    if output_format == "JPEG":
        # JPEG does not support alpha; convert to RGB
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
    elif output_format == "PNG":
        if img.mode not in ("RGB", "RGBA", "L", "LA"):
            img = img.convert("RGBA")

    # 9. Re-encode without EXIF (this is what strips GPS and all other metadata)
    output_buffer = io.BytesIO()
    save_kwargs: dict[str, object] = {}
    if output_format == "JPEG":
        save_kwargs["quality"] = 85
        save_kwargs["optimize"] = True
    img.save(output_buffer, format=output_format, **save_kwargs)
    clean_bytes = output_buffer.getvalue()

    logger.debug(
        "Image validated: format=%s, dimensions=%dx%d, "
        "original=%d bytes, stripped=%d bytes",
        output_format,
        width,
        height,
        len(raw_bytes),
        len(clean_bytes),
    )

    return ImagePayload(
        content=clean_bytes,
        format=output_format,
        width_px=width,
        height_px=height,
        size_bytes=len(clean_bytes),
    )
