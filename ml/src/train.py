import json
from pathlib import Path
import tensorflow as tf

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = REPO_ROOT / "ml" / "configs" / "species.json"
MODEL_OUT = REPO_ROOT / "ml" / "checkpoints" / "mobilenetv2_flora.keras"
DATA_ROOT = Path.home() / "data" / "flora_pipeline" / "splits"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_datasets(img_size: list[int], batch_size: int, seed: int):
    train_ds = tf.keras.utils.image_dataset_from_directory(
        DATA_ROOT / "train",
        image_size=tuple(img_size),
        batch_size=batch_size,
        shuffle=True,
        seed=seed,
        label_mode="categorical",
    )
    val_ds = tf.keras.utils.image_dataset_from_directory(
        DATA_ROOT / "val",
        image_size=tuple(img_size),
        batch_size=batch_size,
        shuffle=False,
        label_mode="categorical",
    )

    class_names = train_ds.class_names
    autotune = tf.data.AUTOTUNE
    train_ds = train_ds.prefetch(buffer_size=autotune)
    val_ds = val_ds.prefetch(buffer_size=autotune)
    return train_ds, val_ds, class_names


def build_model(img_size: list[int], num_classes: int) -> tf.keras.Model:
    inputs = tf.keras.Input(shape=(img_size[0], img_size[1], 3))

    augmentation = tf.keras.Sequential(
        [
            tf.keras.layers.RandomFlip("horizontal"),
            tf.keras.layers.RandomRotation(0.15),
            tf.keras.layers.RandomZoom(0.15),
            tf.keras.layers.RandomContrast(0.15),
        ],
        name="data_augmentation",
    )

    x = augmentation(inputs)
    x = tf.keras.applications.mobilenet_v2.preprocess_input(x)

    base_model = tf.keras.applications.MobileNetV2(
        input_shape=(img_size[0], img_size[1], 3),
        include_top=False,
        weights="imagenet",
    )
    base_model.trainable = False

    x = base_model(x, training=False)
    x = tf.keras.layers.GlobalAveragePooling2D()(x)
    x = tf.keras.layers.Dropout(0.3)(x)
    outputs = tf.keras.layers.Dense(num_classes, activation="softmax")(x)

    return tf.keras.Model(inputs, outputs)


def main() -> None:
    cfg = load_config()
    img_size = cfg.get("img_size", [224, 224])
    batch_size = cfg.get("batch_size", 32)
    seed = cfg.get("seed", 42)
    num_classes = len(cfg["species"])

    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    train_ds, val_ds, class_names = build_datasets(img_size, batch_size, seed)

    if len(class_names) != num_classes:
        print(
            f"Warning: Found {len(class_names)} folders in train/ vs {num_classes} in species.json"
        )

    model = build_model(img_size, len(class_names))
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss="categorical_crossentropy",
        metrics=["accuracy"],
    )

    callbacks = [
        tf.keras.callbacks.ModelCheckpoint(
            filepath=str(MODEL_OUT),
            monitor="val_accuracy",
            save_best_only=True,
            verbose=1,
        ),
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss",
            patience=5,
            restore_best_weights=True,
        ),
    ]

    model.fit(
        train_ds,
        validation_data=val_ds,
        epochs=15,
        callbacks=callbacks,
    )
    print(f"\nTraining complete. Best checkpoint saved to: {MODEL_OUT}")


if __name__ == "__main__":
    main()
