"""Taxonomic label validation utility for FloraMW.

Validates the ML team's proposed class labels (scientific species names)
against the FloraMW botanical catalogue before training begins.

Usage (from the backend directory):
    python -m app.core.taxonomy_check --labels path/to/labels.json

Or programmatically:
    from app.core.taxonomy_check import validate_labels, load_labels_file
    result = await validate_labels(db, labels_map)

Expected labels.json format:
    {
        "0": "Faidherbia albida",
        "1": "Adansonia digitata",
        "2": "Hibiscus rosa-sinensis"
    }

The class index can be an integer or string key. The value must be a
botanical scientific name string. The utility produces a machine-readable
JSON validation report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@dataclass
class LabelValidationReport:
    """Machine-readable report of label validation results."""

    total_labels: int = 0
    matched_count: int = 0
    unmatched_count: int = 0
    duplicate_count: int = 0
    invalid_count: int = 0

    matched: List[Dict[str, Any]] = field(default_factory=list)
    unmatched: List[Dict[str, Any]] = field(default_factory=list)
    duplicates: List[Dict[str, Any]] = field(default_factory=list)
    invalid: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def is_fully_matched(self) -> bool:
        return self.unmatched_count == 0 and self.duplicate_count == 0 and self.invalid_count == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": {
                "total_labels": self.total_labels,
                "matched_count": self.matched_count,
                "unmatched_count": self.unmatched_count,
                "duplicate_count": self.duplicate_count,
                "invalid_count": self.invalid_count,
                "fully_matched": self.is_fully_matched,
            },
            "matched": self.matched,
            "unmatched": self.unmatched,
            "duplicates": self.duplicates,
            "invalid": self.invalid,
        }


def load_labels_file(path: str | Path) -> Dict[str, str]:
    """Load and parse a labels.json file.

    Args:
        path: Path to the JSON file mapping class indices to scientific names.

    Returns:
        Dict mapping string class index to scientific name.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file is not valid JSON or has unexpected structure.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Labels file not found: {p}")

    try:
        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Labels file is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"Labels file must be a JSON object mapping class indices to scientific names. "
            f"Got: {type(data).__name__}"
        )

    # Normalize all keys to strings
    return {str(k): v for k, v in data.items()}


async def validate_labels(
    db,
    labels_map: Dict[str, str],
) -> LabelValidationReport:
    """Validate class labels against the botanical catalogue.

    Args:
        db: SQLAlchemy AsyncSession.
        labels_map: Dict mapping class index strings to scientific name strings.

    Returns:
        LabelValidationReport with match details.
    """
    from sqlalchemy import func, select
    from app.identification.provider import normalise_scientific_name
    from app.models.plant import Plant

    report = LabelValidationReport(total_labels=len(labels_map))

    seen_normalised: Dict[str, str] = {}  # normalised_name → first class index

    for class_idx, raw_name in labels_map.items():
        # Validate entry type
        if not isinstance(raw_name, str) or not raw_name.strip():
            report.invalid.append({
                "class_index": class_idx,
                "value": raw_name,
                "reason": "Must be a non-empty string scientific name.",
            })
            report.invalid_count += 1
            continue

        normalised = normalise_scientific_name(raw_name)

        # Check for duplicates within the label map
        if normalised in seen_normalised:
            report.duplicates.append({
                "class_index": class_idx,
                "scientific_name": raw_name,
                "normalised": normalised,
                "first_seen_at_index": seen_normalised[normalised],
            })
            report.duplicate_count += 1
            continue

        seen_normalised[normalised] = class_idx

        # Query catalogue
        stmt = select(Plant).where(
            func.lower(func.trim(Plant.scientific_name)) == normalised,
            Plant.is_published.is_(True),
        )
        result = await db.execute(stmt)
        plant = result.scalar_one_or_none()

        if plant is not None:
            report.matched.append({
                "class_index": class_idx,
                "scientific_name": raw_name,
                "normalised": normalised,
                "catalogue_plant_id": plant.id,
                "catalogue_common_name": plant.common_name_en,
                "catalogue_family": plant.family,
            })
            report.matched_count += 1
        else:
            report.unmatched.append({
                "class_index": class_idx,
                "scientific_name": raw_name,
                "normalised": normalised,
                "note": (
                    "Species not found in FloraMW catalogue. "
                    "Review spelling, or add this species to the catalogue "
                    "after verification by a qualified botanist."
                ),
            })
            report.unmatched_count += 1

    return report


async def _run_cli(labels_path: str, output_path: Optional[str]) -> int:
    """Entry point for command-line invocation."""
    from app.core.database import AsyncSessionLocal, async_engine

    try:
        labels_map = load_labels_file(labels_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Validating {len(labels_map)} labels against FloraMW botanical catalogue...")

    try:
        async with AsyncSessionLocal() as db:
            report = await validate_labels(db, labels_map)
    finally:
        await async_engine.dispose()

    result_dict = report.to_dict()
    output_json = json.dumps(result_dict, indent=2)

    if output_path:
        Path(output_path).write_text(output_json, encoding="utf-8")
        print(f"Report written to: {output_path}")
    else:
        print(output_json)

    summary = result_dict["summary"]
    print(
        f"\nSummary: {summary['matched_count']} matched, "
        f"{summary['unmatched_count']} unmatched, "
        f"{summary['duplicate_count']} duplicates, "
        f"{summary['invalid_count']} invalid.",
        file=sys.stderr,
    )

    return 0 if report.is_fully_matched else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate ML team class labels against the FloraMW botanical catalogue."
    )
    parser.add_argument(
        "--labels",
        required=True,
        help='Path to labels.json (format: {"0": "Species name", ...})',
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional path to write JSON report. Prints to stdout if not specified.",
    )
    args = parser.parse_args()

    exit_code = asyncio.run(_run_cli(args.labels, args.output))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
