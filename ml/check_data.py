from pathlib import Path
from PIL import Image
import hashlib, collections

root = Path("data/raw")
extensions = {".jpg", ".jpeg", ".png"}

counts = collections.Counter()
broken, too_small, duplicates = [], [], []
seen_hashes = {}

for p in root.rglob("*"):
    if p.suffix.lower() not in extensions:
        continue

    # 1. Can the image be opened?
    try:
        with Image.open(p) as im:
            im.verify()
        with Image.open(p) as im:
            width, height = im.size
    except Exception:
        broken.append(p)
        continue

    # 2. Is it too small to be useful?
    if min(width, height) < 64:
        too_small.append(p)

    # 3. Is it an exact duplicate of another file?
    file_hash = hashlib.md5(p.read_bytes()).hexdigest()
    if file_hash in seen_hashes:
        duplicates.append(p)
    else:
        seen_hashes[file_hash] = p

    counts[p.parent.name] += 1

print("\n=== PHOTOS PER FLOWER ===")
for name, n in sorted(counts.items()):
    print(f"{name:12} {n}")

print("\nBroken files:    ", len(broken))
print("Too small:       ", len(too_small))
print("Exact duplicates:", len(duplicates))

# Move problem files to a quarantine folder instead of deleting them
quarantine = Path("data/quarantine")
quarantine.mkdir(parents=True, exist_ok=True)
for p in set(broken + too_small + duplicates):
    if p.exists():
        p.rename(quarantine / f"{p.parent.name}_{p.name}")

print("\nProblem files moved to data/quarantine")