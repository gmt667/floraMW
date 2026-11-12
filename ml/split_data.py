from pathlib import Path
import shutil, random
from sklearn.model_selection import train_test_split

random.seed(42)  # makes the split the same every time
raw = Path("data/raw")
out_root = Path("data/processed")

if out_root.exists():
    shutil.rmtree(out_root)  # start fresh each time

for class_folder in [d for d in raw.iterdir() if d.is_dir()]:
    files = list(class_folder.glob("*"))

    # 70% train, 15% validation, 15% test
    train, temp = train_test_split(files, test_size=0.30, random_state=42)
    val, test = train_test_split(temp, test_size=0.50, random_state=42)

    for split_name, group in [("train", train), ("val", val), ("test", test)]:
        dest = out_root / split_name / class_folder.name
        dest.mkdir(parents=True, exist_ok=True)
        for f in group:
            shutil.copy(f, dest / f.name)

    print(f"{class_folder.name:12} train={len(train)} val={len(val)} test={len(test)}")

print("\nDone. Check the data/processed folder.")