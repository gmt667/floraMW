import json
from pathlib import Path
import tensorflow as tf

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = REPO_ROOT / "ml" / "configs" / "species.json"
MODEL_PATH = REPO_ROOT / "ml" / "checkpoints" / "mobilenetv2_flora.keras"
VAL_DIR = Path.home() / "data" / "flora_pipeline" / "splits" / "val"
EXPORT_DIR = REPO_ROOT / "ml" / "exports"
TFLITE_OUT = EXPORT_DIR / "mobilenetv2_flora.tflite"
LABELS_OUT = EXPORT_DIR / "labels.txt"


def main() -> None:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Checkpoint not found at {MODEL_PATH}")

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    # Match the exact alphabetical class order used by image_dataset_from_directory
    val_ds = tf.keras.utils.image_dataset_from_directory(
        VAL_DIR,
        image_size=(224, 224),
        batch_size=32,
        shuffle=False,
        label_mode="categorical",
    )
    class_names = val_ds.class_names
    LABELS_OUT.write_text("\n".join(class_names) + "\n", encoding="utf-8")

    model = tf.keras.models.load_model(MODEL_PATH)

    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    tflite_model = converter.convert()

    TFLITE_OUT.write_bytes(tflite_model)
    print(f"Exported TFLite model: {TFLITE_OUT} ({len(tflite_model) / (1024 * 1024):.2f} MB)")
    print(f"Exported class labels: {LABELS_OUT} ({len(class_names)} classes)")


if __name__ == "__main__":
    main()
