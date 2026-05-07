import logging
from typing import Dict, Any
import numpy as np

logger = logging.getLogger(__name__)

class FireSmokeDetector:
    def __init__(self, model_path: str, conf_threshold: float = 0.40):
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self.model = None
        self.ready = False

        self._load_model()

    def _load_model(self):
        try:
            from ultralytics import YOLO
            self.model = YOLO(self.model_path)
            self.ready = True
            logger.info(f"[FIRE_SMOKE] YOLO model loaded successfully from {self.model_path}")
        except ImportError:
            logger.error("[FIRE_SMOKE] ultralytics package not found. Cannot load YOLO.")
        except Exception as e:
            logger.error(f"[FIRE_SMOKE] Failed to load YOLO model: {e}", exc_info=True)

    def is_ready(self) -> bool:
        return self.ready

    def predict_frame(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Detects fire and smoke in the given BGR frame.
        """
        result = {
            "fire_detected": False,
            "smoke_detected": False,
            "fire_confidence": 0.0,
            "smoke_confidence": 0.0,
            "boxes": []
        }

        if not self.ready or self.model is None:
            return result

        try:
            results = self.model.predict(
                source=frame,
                conf=self.conf_threshold,
                verbose=False
            )

            if len(results) > 0:
                boxes = results[0].boxes
                names = self.model.names

                highest_fire_conf = 0.0
                highest_smoke_conf = 0.0

                for box in boxes:
                    cls_id = int(box.cls[0].item())
                    conf = float(box.conf[0].item())
                    label = names[cls_id].lower()

                    if "fire" in label:
                        result["fire_detected"] = True
                        if conf > highest_fire_conf:
                            highest_fire_conf = conf
                    elif "smoke" in label:
                        result["smoke_detected"] = True
                        if conf > highest_smoke_conf:
                            highest_smoke_conf = conf

                    result["boxes"].append({
                        "label": label,
                        "confidence": conf,
                        "coords": box.xyxy[0].tolist()
                    })

                result["fire_confidence"] = highest_fire_conf
                result["smoke_confidence"] = highest_smoke_conf

        except Exception as e:
            logger.error(f"[FIRE_SMOKE] Inference error: {e}", exc_info=True)

        return result
