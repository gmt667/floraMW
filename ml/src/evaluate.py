import json
from pathlib import Path
import numpy as np
import tensorflow as tf
from sklearn.metrics import classification_report, confusion_matrix

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = REPO_ROOT / "ml" / "configs" / "species.json"
MODEL_PATH = REPO_ROOT / "ml" / "checkpoints" / "mobilenetv2_flora.keras"
VAL_DIR = Path.home() / "data" / "flora_pipeline" / "splits" / "val"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    cfg = load_config()
    img_size = tuple(cfg.get("img_size", [224, 224]))
    batch_size = cfg.get("batch_size", 32)

    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Checkpoint not found at {MODEL_PATH}")

    val_ds = tf.keras.utils.image_dataset_from_directory(
        VAL_DIR,
        image_size=img_size,
        batch_size=batch_size,
        shuffle=False,
        label_mode="categorical",
    )
    class_names = val_ds.class_names

    model = tf.keras.models.load_model(MODEL_PATH)
    loss, acc = model.evaluate(val_ds, verbose=0)
    print(f"\nValidation Loss: {loss:.4f} | Validation Top-1 Accuracy: {acc:.4f}\n")

    y_true_list = []
    y_prob_list = []
    for x_batch, y_batch in val_ds:
        probs = model.predict(x_batch, verbose=0)
        y_prob_list.append(probs)
        y_true_list.append(np.argmax(y_batch.numpy(), axis=1))

    y_true = np.concatenate(y_true_list)
    y_probs = np.concatenate(y_prob_list)
    y_pred = np.argmax(y_probs, axis=1)

    labels = list(range(len(class_names)))
    print("=== Per-Class Classification Report ===")
    print(
        classification_report(
            y_true,
            y_pred,
            labels=labels,
            target_names=class_names,
            digits=3,
            zero_division=0,
        )
    )

    cm = confusion_matrix(y_true, y_pred, labels=labels)
    confusions = []
    for i in range(len(class_names)):
        for j in range(len(class_names)):
            if i != j and cm[i, j] > 0:
                confusions.append((cm[i, j], class_names[i], class_names[j]))

    confusions.sort(reverse=True)
    print("=== Top Misclassifications (True -> Predicted) ===")
    for count, true_cls, pred_cls in confusions[:15]:
        print(f"  {count:2d}x : {true_cls}  -->  {pred_cls}")


if __name__ == "__main__":
    main()
