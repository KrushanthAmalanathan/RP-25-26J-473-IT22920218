from ultralytics import YOLO

model = YOLO("models/accident_best.pt")
print(f"Task type: {model.task}")
print(f"Names: {model.names}")
