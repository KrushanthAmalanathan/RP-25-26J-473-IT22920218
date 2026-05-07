import os
import numpy as np
from ultralytics import YOLO


class AccidentDetector:
    def __init__(self, model_path: str, conf_threshold: float = 0.8, consecutive_frames: int = 3):
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self.consecutive_frames = consecutive_frames
        self.model = None
        self.hit_count = 0

        if os.path.exists(model_path):
            self.model = YOLO(model_path)

    def is_ready(self):
        return self.model is not None

    def _normalize_label(self, label: str) -> str:
        return str(label).strip().lower().replace(" ", "_")

    def predict_frame(self, frame):
        if self.model is None:
            return {
                "active": False,
                "confidence": 0.0,
                "label": "Non_Accident",
                "consecutive_hits": 0,
                "area": "west_camera_full_frame",
            }

        try:
            results = self.model.predict(frame, verbose=False)
            names = results[0].names
            
            is_accident = False
            highest_conf = 0.0
            best_label = "Non_Accident"

            if results[0].probs is not None:
                # Classification model
                probs_list = results[0].probs.data.tolist()
                top_idx = int(np.argmax(probs_list))
                top_conf = float(probs_list[top_idx])
                top_label = names[top_idx]
                normalized = self._normalize_label(top_label)
                if normalized in {"accident", "crash", "collision"} and top_conf >= self.conf_threshold:
                    is_accident = True
                    highest_conf = top_conf
                    best_label = top_label
            elif results[0].boxes is not None and len(results[0].boxes) > 0:
                # Detection model
                for box in results[0].boxes:
                    conf = float(box.conf[0])
                    cls = int(box.cls[0])
                    label = str(names[cls])
                    normalized = self._normalize_label(label)
                    
                    if normalized in {"accident", "crash", "collision"} and conf >= self.conf_threshold:
                        if conf > highest_conf:
                            highest_conf = conf
                            best_label = label
                            is_accident = True

            if is_accident:
                self.hit_count += 1
            else:
                self.hit_count = 0

            active = self.hit_count >= self.consecutive_frames

            return {
                "active": active,
                "confidence": highest_conf,
                "label": best_label,
                "consecutive_hits": self.hit_count,
                "area": "west_camera_full_frame",
            }

        except Exception:
            return {
                "active": False,
                "confidence": 0.0,
                "label": "Non_Accident",
                "consecutive_hits": 0,
                "area": "west_camera_full_frame",
            }