import json
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torchvision import datasets, transforms, models


def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print("Training on:", device)

    mean, std = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]

    # Training photos get random changes (augmentation) so the model sees variety
    train_tf = transforms.Compose([
        transforms.RandomResizedCrop(224, scale=(0.7, 1.0)),
        transforms.RandomHorizontalFlip(),
        transforms.RandomRotation(15),
        transforms.ColorJitter(0.2, 0.2, 0.2),
        transforms.ToTensor(),
        transforms.Normalize(mean, std),
    ])

    # Validation photos are only resized, so they look like real photos
    eval_tf = transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(mean, std),
    ])

    train_ds = datasets.ImageFolder("data/processed/train", train_tf)
    val_ds = datasets.ImageFolder("data/processed/val", eval_tf)
    train_dl = DataLoader(train_ds, batch_size=32, shuffle=True, num_workers=0)
    val_dl = DataLoader(val_ds, batch_size=32, num_workers=0)

    print("Flowers found:", train_ds.classes)
    print("Train photos:", len(train_ds), "| Validation photos:", len(val_ds))

    # Save the flower names so predict.py and evaluate.py can use them
    with open("classes.json", "w") as f:
        json.dump(train_ds.classes, f)

    # Borrow a pretrained model (ResNet18), freeze it, replace the last layer
    model = models.resnet18(weights=models.ResNet18_Weights.DEFAULT)
    for p in model.parameters():
        p.requires_grad = False
    model.fc = nn.Linear(model.fc.in_features, len(train_ds.classes))
    model = model.to(device)

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.fc.parameters(), lr=1e-3)

    def run_epoch(dl, training):
        model.train(training)
        total, correct, loss_sum = 0, 0, 0.0
        with torch.set_grad_enabled(training):
            for x, y in dl:
                x, y = x.to(device), y.to(device)
                out = model(x)
                loss = criterion(out, y)
                if training:
                    optimizer.zero_grad()
                    loss.backward()
                    optimizer.step()
                loss_sum += loss.item() * len(y)
                correct += (out.argmax(1) == y).sum().item()
                total += len(y)
        return loss_sum / total, correct / total

    EPOCHS = 5
    best_val = 0
    for epoch in range(1, EPOCHS + 1):
        tr_loss, tr_acc = run_epoch(train_dl, True)
        va_loss, va_acc = run_epoch(val_dl, False)
        print(f"epoch {epoch}/{EPOCHS}: train acc {tr_acc:.3f} | val acc {va_acc:.3f}")
        if va_acc > best_val:
            best_val = va_acc
            torch.save(model.state_dict(), "best_model.pt")
            print("  saved best model")

    print("\nDone. Best validation accuracy:", round(best_val, 3))


if __name__ == "__main__":  # required on Windows
    main()