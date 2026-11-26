import json
import random
import shutil
from pathlib import Path
from icrawler.builtin import BingImageCrawler
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = REPO_ROOT / "ml" / "configs" / "species.json"
DATA_ROOT = Path.home() / "data" / "flora_pipeline"
MIN_DIM = 224


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def slug_to_query(species_slug: str) -> str:
    cleaned = species_slug.replace("_", " ").replace("-", " ").strip()
    return f"{cleaned} flower plant"


def scrape_species(species_slug: str, max_num: int = 60) -> None:
    out_dir = DATA_ROOT / "raw" / species_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    crawler = BingImageCrawler(storage={"root_dir": str(out_dir)})
    crawler.crawl(keyword=slug_to_query(species_slug), max_num=max_num)


def sanitize_species(species_slug: str) -> list[Path]:
    src_dir = DATA_ROOT / "raw" / species_slug
    dst_dir = DATA_ROOT / "clean" / species_slug
    dst_dir.mkdir(parents=True, exist_ok=True)

    valid_files: list[Path] = []
    if not src_dir.exists():
        return valid_files

    for file_path in sorted(src_dir.iterdir()):
        if not file_path.is_file():
            continue
        try:
            with Image.open(file_path) as img:
                img.verify()
            with Image.open(file_path) as img:
                w, h = img.size
                if w < MIN_DIM or h < MIN_DIM:
                    continue
                rgb = img.convert("RGB")
                target_path = dst_dir / f"{file_path.stem}.jpg"
                rgb.save(target_path, format="JPEG", quality=90)
                valid_files.append(target_path)
        except Exception:
            continue

    return valid_files


def split_dataset(
    species_slug: str,
    files: list[Path],
    val_ratio: float = 0.2,
    seed: int = 42,
) -> tuple[int, int]:
    rng = random.Random(seed)
    shuffled = sorted(files)
    rng.shuffle(shuffled)

    val_count = max(1, int(len(shuffled) * val_ratio)) if len(shuffled) > 1 else 0
    val_files = shuffled[:val_count]
    train_files = shuffled[val_count:]

    for split_name, split_items in [("train", train_files), ("val", val_files)]:
        split_dir = DATA_ROOT / "splits" / split_name / species_slug
        split_dir.mkdir(parents=True, exist_ok=True)
        for f in split_items:
            shutil.copy2(f, split_dir / f.name)

    return len(train_files), len(val_files)


def main() -> None:
    cfg = load_config()
    seed = cfg.get("seed", 42)
    species_list = cfg["species"]

    print(f"Loaded {len(species_list)} species from {CONFIG_PATH}")
    for sp in species_list:
        print(f"\n=== Processing: {sp} ===")
        scrape_species(sp, max_num=60)
        cleaned = sanitize_species(sp)
        train_n, val_n = split_dataset(sp, cleaned, val_ratio=0.2, seed=seed)
        print(f"Clean: {len(cleaned)} | Train: {train_n} | Val: {val_n}")


if __name__ == "__main__":
    main()
