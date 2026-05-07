# backend/controller/yolo_west_source.py
"""
WEST road vehicle detection using YOLO with background thread processing.

Features:
- Background thread for continuous camera capture
- ROI cropping for consistent counts
- Rolling smoothing to reduce flicker
- Queue metrics (waiting, cleared estimate)
- Congestion tracking
- Safe cached frame serving for API endpoints
"""

import time
import os
import threading
import logging
from collections import defaultdict
from typing import Dict, Optional, Tuple, List
import cv2
import numpy as np
from ultralytics import YOLO

logger = logging.getLogger(__name__)


def norm_label(s):
    """Normalize label: strip, uppercase, remove separators."""
    if s is None:
        return ""
    return str(s).strip().upper().replace("-", "").replace("_", "").replace(" ", "")


# Map short codes -> traffic class (for custom models)
CODE_MAP = {
    "C": "car",
    "V": "car",
    "MC": "bike",
    "TW": "auto",
    "LB": "bus",
    "MB": "bus",
    "HGV": "lorry",
    "HGVM": "lorry",
    "LGV": "truck",
    "MGV": "truck",
    "TR": "truck",
}

# Map full names -> traffic class (for standard COCO or custom datasets)
NAME_MAP = {
    "CAR": "car",
    "VAN": "car",
    "AUTOMOBILE": "car",
    "VEHICLE": "car",
    "MOTORCYCLE": "bike",
    "MOTORBIKE": "bike",
    "BICYCLE": "bike",
    "BIKE": "bike",
    "THREEWHEELER": "auto",
    "THREEWHEEL": "auto",
    "THREEWHEELER": "auto",
    "3WHEELER": "auto",
    "AUTO": "auto",
    "AUTORICKSHAW": "auto",
    "BUS": "bus",
    "MINIBUS": "bus",
    "TRUCK": "truck",
    "TRACTOR": "truck",
    "HEAVYGOODSVEHICLE": "lorry",
    "LIGHTGOODSVEHICLE": "truck",
    "MEDIUMGOODSVEHICLE": "truck",
    "LORRY": "lorry",
    "HGV": "lorry",
}

# Vehicle class weights for congestion (higher = heavier)
VEHICLE_WEIGHTS = {
    "car": 1,
    "bike": 0.5,
    "bus": 3,
    "truck": 2.5,
    "lorry": 2.5,
    "auto": 0.7,
}

# Congestion thresholds (weighted count)
CONGESTION_THRESHOLDS = {
    "LOW": (0, 10),
    "MEDIUM": (10, 25),
    "HIGH": (25, float("inf")),
}


class YoloWestSource:
    """
    Reads laptop cam, runs YOLO, computes WEST road metrics.
    
    Metrics:
    - Counts (vehicles by type)
    - Queue metrics (waiting, cleared estimate)
    - Smoothing (rolling window)
    - ROI cropping (optional)
    """

    def __init__(
        self,
        model_path: str,
        cam_index: int = 0,
        conf: float = 0.20,
        iou: float = 0.45,
        imgsz: int = 960,
        max_det: int = 100,
        use_tracking: bool = False,
        roi_str: str = "",
        smoothing_window: int = 5,
        enable_smoothing: bool = True,
        resize_width: int = 960,
        source_mode: str = "webcam",
        video_path: Optional[str] = None,
        loop_video: bool = False,
    ):
        """
        Initialize YOLO source for WEST road with tuning parameters.
        
        Args:
            model_path: Path to YOLO model weights
            cam_index: Camera device index (0=default)
            conf: Detection confidence threshold (0.0-1.0, default 0.20)
            iou: IoU threshold for NMS (0.0-1.0, default 0.45)
            imgsz: Inference image size (default 960)
            max_det: Maximum detections per frame (default 100)
            use_tracking: Use YOLO track() instead of predict() for stability
            roi_str: ROI as "x1,y1,x2,y2" or empty for full frame
            smoothing_window: Number of snapshots to keep for smoothing
            enable_smoothing: Enable rolling smoothing
            resize_width: Resize frame to this width before YOLO (0=disabled, default 960)
            source_mode: "webcam" or "video"
            video_path: Path to video file (required if source_mode="video")
            loop_video: Loop video when it ends (only for video mode)
        """
        self.model = YOLO(model_path)
        self.cam_index = cam_index
        self.conf = conf
        self.iou = iou
        self.imgsz = imgsz
        self.max_det = max_det
        self.use_tracking = use_tracking
        self.cap = None
        self.resize_width = resize_width
        
        # Source mode configuration (Task 3)
        self.source_mode = source_mode.lower()
        self.video_path = video_path
        self.loop_video = loop_video

        # ROI configuration
        self.roi = self._parse_roi(roi_str)
        self.roi_active = self.roi is not None

        # Smoothing (rolling window)
        self.enable_smoothing = enable_smoothing
        self.smoothing_window = max(1, smoothing_window)
        self.count_history: List[Dict[str, int]] = []

        # Metrics tracking
        self.last_total_count = 0
        self.last_counts = defaultdict(int)
        self.last_ts = 0.0
        self.cleared_count = 0
        
        # Thread-safe cached frame and detection storage
        self._lock = threading.Lock()
        self.latest_jpeg = None
        self.latest_raw_jpeg = None
        self.latest_counts = {}
        self.latest_detections = []
        self.last_frame_ts = 0.0
        self.camera_ok = False
        self.error_message = ""
        
        # Debug tracking
        self.frame_count = 0
        self.total_raw_boxes = 0
        self.total_mapped_boxes = 0
        self.unique_raw_labels = set()  # Track all unique raw labels seen
        self.logged_unmapped_labels = set() # Track labels already warned about
        self.last_debug_log = 0  # Timestamp for periodic debug logging
        
        # Log model configuration at startup
        logger.info(f"YOLO model loaded: {model_path}")
        logger.info(f"Model classes: {list(self.model.names.values())}")
        logger.info(f"YOLO inference config: conf={self.conf}, iou={self.iou}, imgsz={self.imgsz}, max_det={self.max_det}")
        logger.info(f"Tracking mode: {self.use_tracking}, Resize width: {resize_width}, ROI active: {self.roi_active}")
        
        # Background thread
        self._thread = None
        self._running = False

    def _parse_roi(self, roi_str: str) -> Optional[Tuple[int, int, int, int]]:
        """Parse ROI from string format 'x1,y1,x2,y2'."""
        if not roi_str or not roi_str.strip():
            return None
        try:
            parts = [int(x.strip()) for x in roi_str.split(",")]
            if len(parts) == 4:
                x1, y1, x2, y2 = parts
                # Ensure valid coordinates
                if x1 >= 0 and y1 >= 0 and x2 > x1 and y2 > y1:
                    return (x1, y1, x2, y2)
        except (ValueError, AttributeError):
            pass
        return None

    def start(self):
        """Start background camera thread."""
        if self._running:
            logger.warning("Camera thread already running")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._camera_loop, daemon=True)
        self._thread.start()
        logger.info(f"WEST camera started, index={self.cam_index}, model={self.model.model_name}, fps_target=5")

    def stop(self):
        """Stop background camera thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        
        if self.cap:
            self.cap.release()
        self.cap = None
        logger.info("WEST camera stopped")
    
    def _camera_loop(self):
        """Background thread loop: capture, detect, annotate, encode frames."""
        try:
            # Open camera once
            if self.source_mode == "video":
                if not self.video_path or not os.path.exists(self.video_path):
                    self.camera_ok = False
                    self.error_message = f"Video file not found: {self.video_path}"
                    logger.error(self.error_message)
                    return
                logger.info(f"Opening video file: {self.video_path}")
                self.cap = cv2.VideoCapture(self.video_path)
            else:
                # Try MSMF first (default), then DSHOW fallback on Windows
                logger.info(f"Opening webcam source (index={self.cam_index})...")
                self.cap = cv2.VideoCapture(self.cam_index)
                if not self.cap.isOpened():
                    logger.warning(f"Could not open camera with default backend, trying CAP_DSHOW...")
                    self.cap = cv2.VideoCapture(self.cam_index, cv2.CAP_DSHOW)
            
            if not self.cap.isOpened():
                self.camera_ok = False
                self.error_message = f"Could not open {self.source_mode} source (index={self.cam_index})"
                logger.error(f"FATAL: {self.error_message}")
                return
            
            self.camera_ok = True
            self.error_message = ""
            logger.info(f"Camera {self.source_mode} opened successfully")
            
            frame_count = 0
            last_time = time.time()
            target_fps = 5
            frame_interval = 1.0 / target_fps
            
            # Main loop at ~5 FPS
            while self._running:
                now = time.time()
                elapsed = now - last_time
                
                # Rate limiting
                if elapsed < frame_interval:
                    time.sleep(0.01)
                    continue
                
                last_time = now
                frame_count += 1
                
                # Read frame
                ok, frame = self.cap.read()
                if not ok:
                    # Handle video loop
                    if self.source_mode == "video" and self.loop_video:
                        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ok, frame = self.cap.read()
                    
                    if not ok:
                        logger.warning("Failed to read frame from camera")
                        time.sleep(0.1)
                        continue
                
                # Crop ROI if configured
                if self.roi_active:
                    frame = self._crop_roi(frame)
                
                # Resize for faster processing
                frame = self._resize_frame(frame)
                
                # Detect vehicles
                try:
                    raw_counts, detections, raw_box_count, mapped_labels_log, unmapped_raw_labels = self._detect_vehicles(frame)
                    
                    # Ensure all keys exist
                    counts = {
                        "car": raw_counts.get("car", 0),
                        "bike": raw_counts.get("bike", 0),
                        "bus": raw_counts.get("bus", 0),
                        "truck": raw_counts.get("truck", 0),
                        "lorry": raw_counts.get("lorry", 0),
                        "auto": raw_counts.get("auto", 0),
                    }
                    
                    # Apply smoothing
                    smoothed_counts = self._smooth_counts(counts)
                    
                    # Compute metrics
                    metrics = self._compute_metrics(smoothed_counts)
                    
                    # Annotate frame with detections and debug info
                    annotated = self._annotate_frame(frame, detections, raw_box_count)
                    
                    # Encode to JPEG
                    try:
                        _, jpeg_buffer = cv2.imencode('.jpg', annotated, 
                                                     [cv2.IMWRITE_JPEG_QUALITY, 85])
                        jpeg_bytes = jpeg_buffer.tobytes()
                        
                        _, raw_jpeg_buffer = cv2.imencode('.jpg', frame, 
                                                     [cv2.IMWRITE_JPEG_QUALITY, 85])
                        raw_jpeg_bytes = raw_jpeg_buffer.tobytes()
                    except Exception as e:
                        logger.error(f"JPEG encoding error: {e}")
                        jpeg_bytes = None
                        raw_jpeg_bytes = None
                    
                    # Store in thread-safe manner
                    with self._lock:
                        self.latest_jpeg = jpeg_bytes
                        self.latest_raw_jpeg = raw_jpeg_bytes
                        self.latest_counts = smoothed_counts
                        self.latest_detections = detections[:50]  # Limit to 50
                        self.last_frame_ts = time.time()
                    
                    # Log every 5 frames
                    if self.frame_count % 5 == 0:
                        logger.info(f"[YOLO_STORE] Frame {self.frame_count}: detections={len(detections)}, "
                                   f"mapped={[d['cls_mapped'] for d in detections]}, "
                                   f"counts={smoothed_counts}, total={sum(smoothed_counts.values())}")
                    
                    # Log detailed mapping on frames with detections
                    if raw_box_count > 0 and mapped_labels_log:
                        logger.info(f"[MAPPED] Frame {self.frame_count}: {', '.join(mapped_labels_log)}")
                    if unmapped_raw_labels:
                        logger.warning(f"[UNMAPPED] Frame {self.frame_count}: {', '.join(unmapped_raw_labels)}")
                    
                    # Update tracking
                    current_total = sum(smoothed_counts.values())
                    if current_total != self.last_total_count:
                        self.cleared_count = metrics["cleared_last_interval"]
                    
                    self.last_total_count = current_total
                    self.last_counts = smoothed_counts
                    self.last_ts = time.time()
                    
                except Exception as e:
                    logger.error(f"Detection/processing error: {e}")
                    time.sleep(0.1)
                    continue
        
        except Exception as e:
            self.camera_ok = False
            self.error_message = str(e)
            logger.error(f"Camera thread fatal error: {e}")
        finally:
            if self.cap:
                self.cap.release()
            self.cap = None
            self.camera_ok = False

    def _crop_roi(self, frame: np.ndarray) -> np.ndarray:
        """Apply ROI cropping if configured."""
        if not self.roi_active or self.roi is None:
            return frame
        
        x1, y1, x2, y2 = self.roi
        h, w = frame.shape[:2]
        
        # Clamp to frame bounds
        x1 = max(0, min(x1, w))
        x2 = max(0, min(x2, w))
        y1 = max(0, min(y1, h))
        y2 = max(0, min(y2, h))
        
        return frame[y1:y2, x1:x2]

    def _resize_frame(self, frame: np.ndarray) -> np.ndarray:
        """Resize frame for YOLO processing. If resize_width=0, returns original."""
        if self.resize_width == 0:
            return frame  # No resizing
        
        h, w = frame.shape[:2]
        if w > self.resize_width:
            aspect = h / w
            new_h = int(self.resize_width * aspect)
            frame = cv2.resize(frame, (self.resize_width, new_h), interpolation=cv2.INTER_LINEAR)
        return frame
    
    def _annotate_frame(self, frame: np.ndarray, detections: List[Dict], raw_box_count: int = 0) -> np.ndarray:
        """Draw bounding boxes, labels, and debug info on frame."""
        annotated = frame.copy()
        h, w = annotated.shape[:2]
        
        # Color map for vehicle types
        colors = {
            "car": (0, 255, 0),      # Green
            "bike": (255, 255, 0),   # Cyan
            "bus": (0, 0, 255),      # Red
            "truck": (255, 0, 255),  # Magenta
            "lorry": (255, 0, 128),  # Purple
            "auto": (0, 255, 255),   # Yellow
            "unknown": (128, 128, 128),  # Gray
        }
        
        # Draw detection boxes
        mapped_count = 0
        for det in detections:
            x1, y1, x2, y2 = det["x1"], det["y1"], det["x2"], det["y2"]
            cls_mapped = det["cls_mapped"]
            cls_raw = det.get("cls_raw", "")
            conf = det["conf"]
            
            if cls_mapped != "unknown":
                mapped_count += 1
            
            color = colors.get(cls_mapped, (255, 255, 255))
            
            # Draw bounding box
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            
            # Draw label (show raw if unmapped)
            if cls_mapped == "unknown":
                label = f"{cls_raw} {conf:.2f}"
            else:
                label = f"{cls_mapped} {conf:.2f}"
            
            (label_w, label_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(annotated, (x1, y1 - 20), (x1 + label_w + 10, y1), color, -1)
            
            # Draw label text
            cv2.putText(annotated, label, (x1 + 5, y1 - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        
        # Add debug overlay at top (line 1)
        debug_text1 = f"conf={self.conf:.2f}, iou={self.iou:.2f}, imgsz={self.imgsz}, raw={raw_box_count}, mapped={mapped_count}"
        cv2.putText(annotated, debug_text1, (10, 25),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        
        # Add unique raw labels (line 2)
        unique_labels_list = sorted(self.unique_raw_labels)[:5]
        unique_labels_str = ", ".join(unique_labels_list)
        debug_text2 = f"raw_labels: {unique_labels_str}"
        cv2.putText(annotated, debug_text2, (10, 55),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        
        return annotated

    def _detect_vehicles(self, frame: np.ndarray) -> Tuple[Dict[str, int], List[Dict]]:
        """Run YOLO detection on frame and return counts + detection metadata."""
        counts = defaultdict(int)
        detections = []
        raw_box_count = 0
        unmapped_raw_labels = set()
        mapped_labels_log = []
        
        try:
            # Choose predict or track based on configuration
            if self.use_tracking:
                results = self.model.track(frame, conf=self.conf, iou=self.iou, imgsz=self.imgsz, 
                                          max_det=self.max_det, verbose=False, persist=True)
            else:
                results = self.model.predict(frame, conf=self.conf, iou=self.iou, imgsz=self.imgsz,
                                            max_det=self.max_det, verbose=False)
            
            # Extract detections from results
            if results and len(results) > 0:
                r = results[0]
                raw_box_count = len(r.boxes) if hasattr(r, 'boxes') else 0
                
                if raw_box_count > 0:
                    for b in r.boxes:
                        cls_id = int(b.cls)
                        raw = self.model.names.get(cls_id, "unknown")
                        raw_norm = norm_label(raw)
                        
                        # Track unique raw labels
                        self.unique_raw_labels.add(raw)
                        
                        # Try code map first, then name map
                        traffic_cls = CODE_MAP.get(raw_norm)
                        if not traffic_cls:
                            traffic_cls = NAME_MAP.get(raw_norm)
                        
                        # Extract box coordinates
                        box = b.xyxy[0].cpu().numpy() if hasattr(b, 'xyxy') else [0, 0, 0, 0]
                        conf_val = float(b.conf[0]) if hasattr(b, 'conf') else 0.0
                        
                        # Always include detection (even if unmapped for debugging)
                        detection_entry = {
                            "cls_raw": raw,
                            "cls_mapped": traffic_cls if traffic_cls else "unknown",
                            "conf": conf_val,
                            "x1": int(box[0]),
                            "y1": int(box[1]),
                            "x2": int(box[2]),
                            "y2": int(box[3]),
                        }
                        detections.append(detection_entry)
                        
                        # Only count if successfully mapped to known traffic class
                        if traffic_cls and traffic_cls in ["car", "bike", "bus", "truck", "lorry", "auto"]:
                            counts[traffic_cls] += 1
                            mapped_labels_log.append(f"{raw}→{traffic_cls}")
                        else:
                            # Track unmapped for debugging
                            unmapped_raw_labels.add(f"{raw}({raw_norm})")
            
            # Update tracking statistics
            self.total_raw_boxes += raw_box_count
            mapped_count = sum(1 for d in detections if d["cls_mapped"] != "unknown")
            self.total_mapped_boxes += mapped_count
            self.frame_count += 1
            
            # Periodic debug logging (every 5 seconds)
            now = time.time()
            if now - self.last_debug_log >= 5.0:
                self.last_debug_log = now
                unique_labels_str = ", ".join(sorted(self.unique_raw_labels)[:10])
                logger.info(f"[Debug] Frame {self.frame_count}: unique_raw_labels=[{unique_labels_str}], "
                           f"raw_boxes={raw_box_count}, mapped={mapped_count}")
            
            # Log unmapped classes only once or occasionally to avoid spam
            if unmapped_raw_labels:
                new_unmapped = [ul for ul in unmapped_raw_labels if ul not in self.logged_unmapped_labels]
                if new_unmapped:
                    logger.warning(f"Frame {self.frame_count}: New unmapped_labels={new_unmapped}")
                    for ul in new_unmapped:
                        self.logged_unmapped_labels.add(ul)
            
        except Exception as e:
            logger.error(f"YOLO detection error on frame {self.frame_count}: {e}", exc_info=True)
        
        return dict(counts), detections, raw_box_count, mapped_labels_log, unmapped_raw_labels

    def _smooth_counts(self, current_counts: Dict[str, int]) -> Dict[str, int]:
        """Apply rolling smoothing to reduce flicker."""
        if not self.enable_smoothing:
            return current_counts
        
        # Add current to history
        self.count_history.append(current_counts.copy())
        
        # Keep window size
        if len(self.count_history) > self.smoothing_window:
            self.count_history.pop(0)
        
        # If not enough samples yet, return current
        if len(self.count_history) < 2:
            return current_counts
        
        # Smooth using median (more robust than mean for outliers)
        smoothed = defaultdict(float)
        for vehicle_type in ["car", "bike", "bus", "truck", "lorry", "auto"]:
            counts = [h.get(vehicle_type, 0) for h in self.count_history]
            # Use median for robustness
            median_count = float(np.median(counts))
            smoothed[vehicle_type] = int(round(median_count))
        
        return dict(smoothed)

    def _compute_metrics(self, counts: Dict[str, int]) -> Dict:
        """Compute queue and cleared metrics."""
        total = sum(counts.values())
        
        # Compute weighted count for congestion
        weighted_count = sum(
            counts.get(vtype, 0) * VEHICLE_WEIGHTS.get(vtype, 1)
            for vtype in ["car", "bike", "bus", "truck", "lorry", "auto"]
        )
        
        # Estimate cleared vehicles (reduction from last frame)
        cleared = 0
        if self.last_total_count > total:
            # Vehicles were cleared
            cleared = min(
                self.last_total_count - total,
                max(5, self.last_total_count // 2),  # Reasonable max
            )
        
        # Determine congestion level
        congestion_level = "LOW"
        for level, (low, high) in CONGESTION_THRESHOLDS.items():
            if low <= weighted_count < high:
                congestion_level = level
                break
        
        # Congestion percentage (0-100)
        max_weighted = 50  # Arbitrary max for percentage calc
        congestion_percent = min(100, int((weighted_count / max_weighted) * 100))
        
        metrics = {
            "waiting_count": total,
            "queue_length": total,
            "cleared_last_interval": cleared,
            "weighted_count": weighted_count,
            "congestion_level": congestion_level,
            "congestion_percent": congestion_percent,
            "smoothed": self.enable_smoothing,
            "roi_active": self.roi_active,
        }
        
        return metrics

    def get_latest_counts(self) -> Dict[str, int]:
        """Get latest vehicle counts from background thread (thread-safe)."""
        with self._lock:
            result = self.latest_counts.copy() if self.latest_counts else {
                "car": 0, "bike": 0, "bus": 0, "truck": 0, "lorry": 0, "auto": 0
            }
        # Log every call to see if this is being called
        total = sum(result.values())
        if total > 0 or self.frame_count % 10 == 0:
            logger.debug(f"[GET_COUNTS] Frame {self.frame_count}: returning counts={result}, total={total}")
        return result
    
    def get_latest_frame_jpeg(self) -> Optional[bytes]:
        """Get latest annotated JPEG frame from background thread (thread-safe)."""
        with self._lock:
            return self.latest_jpeg

    def get_latest_raw_frame_jpeg(self) -> Optional[bytes]:
        """Get latest raw unannotated JPEG frame from background thread (thread-safe)."""
        with self._lock:
            return self.latest_raw_jpeg
    
    def get_status(self) -> Dict:
        """Get camera status (thread-safe)."""
        with self._lock:
            return {
                "camera_ok": self.camera_ok,
                "error_message": self.error_message,
                "last_frame_ts": self.last_frame_ts,
                "detections": self.latest_detections.copy(),
            }
    
    def read_west_counts(self) -> Dict:
        """
        Get WEST road counts and metrics from background thread.
        
        Returns:
            {
                "counts": {car, bike, bus, truck, lorry, auto},
                "west_metrics": {
                    "waiting_count": int,
                    "queue_length": int,
                    "cleared_last_interval": int,
                    "congestion_level": "LOW|MEDIUM|HIGH",
                    "congestion_percent": int (0-100),
                    "smoothed": bool,
                    "roi_active": bool,
                }
            }
        """
        counts = self.get_latest_counts()
        
        # Compute metrics from current counts
        metrics = self._compute_metrics(counts)
        
        return {
            "counts": counts,
            "west_metrics": metrics,
        }

