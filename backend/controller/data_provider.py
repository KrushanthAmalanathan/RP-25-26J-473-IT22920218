"""
Abstraction for road data providers with hybrid YOLO/fake support.

This module provides a RoadDataProvider interface that can be implemented
by different sources (fake generator, real YOLO, SUMO, etc).

The HybridProvider combines:
- WEST: Real YOLO detection from laptop camera (if enabled)
- N/E/S: Fake data generator (unchanged from original system)
"""

from abc import ABC, abstractmethod
import logging
import time
from typing import Dict, Optional

from .state_models import TrafficCounts, RoadVehicleCounts, Road
from .yolo_fake_generator import FakeYOLOGenerator

logger = logging.getLogger(__name__)


class RoadDataProvider(ABC):
    """
    Abstract base for providing road vehicle counts and queue metrics.
    """

    @abstractmethod
    def get_counts(self) -> TrafficCounts:
        """
        Get current vehicle counts by type for all four roads.
        
        Returns:
            TrafficCounts with car, bike, bus, truck, lorry, auto counts per road
        """
        pass

    @abstractmethod
    def get_queue_metrics(self) -> Dict[Road, int]:
        """
        Get current queue lengths for each road.
        
        Returns:
            Dict mapping Road -> queue length (int)
        """
        pass


class HybridProvider(RoadDataProvider):
    """
    Hybrid data provider:
    - WEST: Uses YOLO camera if enabled, falls back to fake data
    - NORTH/EAST/SOUTH: Always uses fake data generator (unchanged)
    """

    def __init__(
        self,
        use_camera_west: bool = False,
        camera_index: int = 0,
        model_path: str = "models/best.pt",
        conf: float = 0.20,
        iou: float = 0.45,
        imgsz: int = 960,
        max_det: int = 100,
        use_tracking: bool = False,
        roi_west: str = "",
        smoothing_enabled: bool = True,
        smoothing_window: int = 5,
        resize_width: int = 960,
        source_mode: str = "webcam",
        video_path: Optional[str] = None,
        loop_video: bool = False,
    ):
        """
        Initialize hybrid provider.
        
        Args:
            use_camera_west: Enable YOLO camera for WEST road
            camera_index: Laptop camera device index
            model_path: Path to YOLO model weights
            conf: YOLO confidence threshold (lower = more detections)
            iou: NMS IoU threshold for overlap filtering
            imgsz: YOLO inference image size (larger = better accuracy)
            max_det: Maximum detections per frame
            use_tracking: Enable temporal tracking mode
            roi_west: ROI as "x1,y1,x2,y2" or empty for full frame
            smoothing_enabled: Enable rolling smoothing
            smoothing_window: Number of frames for smoothing
            resize_width: Resize frame width for performance
            source_mode: "webcam" or "video" (Task 3)
            video_path: Path to video file (Task 3)
            loop_video: Loop video when it ends (Task 3)
        """
        self.use_camera_west = use_camera_west
        self.camera_index = camera_index
        self.model_path = model_path
        self.conf = conf
        self.iou = iou
        self.imgsz = imgsz
        self.max_det = max_det
        self.use_tracking = use_tracking
        self.roi_west = roi_west
        self.smoothing_enabled = smoothing_enabled
        self.smoothing_window = smoothing_window
        self.resize_width = resize_width
        self.source_mode = source_mode
        self.video_path = video_path
        self.loop_video = loop_video

        # Fake generator for N/E/S always, backup for WEST
        self.fake_gen = FakeYOLOGenerator()

        # YOLO source for WEST (if enabled)
        self.yolo_source = None
        self.west_metrics = None
        self.camera_ok = False
        self.last_camera_ts = 0.0
        self.camera_error_count = 0
        self.max_camera_errors = 3  # Fallback after 3 consecutive errors

        if self.use_camera_west:
            self._init_yolo()

    def _init_yolo(self):
        """Initialize YOLO source with error handling."""
        try:
            from .yolo_west_source import YoloWestSource

            self.yolo_source = YoloWestSource(
                model_path=self.model_path,
                cam_index=self.camera_index,
                conf=self.conf,
                iou=self.iou,
                imgsz=self.imgsz,
                max_det=self.max_det,
                use_tracking=self.use_tracking,
                roi_str=self.roi_west,
                smoothing_window=self.smoothing_window,
                enable_smoothing=self.smoothing_enabled,
                resize_width=self.resize_width,
                source_mode=self.source_mode,
                video_path=self.video_path,
                loop_video=self.loop_video,
            )
            self.yolo_source.start()
            self.camera_ok = True
            
            source_info = f"mode={self.source_mode}"
            if self.source_mode == "video":
                source_info += f", video={self.video_path}, loop={self.loop_video}"
            else:
                source_info += f", cam={self.camera_index}"
            
            logger.info(f"YOLO WEST source initialized: {source_info}, model={self.model_path}, "
                       f"roi={'set' if self.roi_west else 'none'}, smoothing={self.smoothing_enabled}")
        except ImportError:
            logger.error("ultralytics not installed, YOLO disabled. Falling back to fake WEST data.")
            self.use_camera_west = False
            self.camera_ok = False
        except Exception as e:
            logger.error(f"Failed to initialize YOLO: {e}. Falling back to fake WEST data.")
            self.use_camera_west = False
            self.camera_ok = False

    def _read_west_from_yolo(self) -> Optional[Dict]:
        """
        Attempt to read WEST counts and metrics from YOLO camera.
        Returns None if camera fails, triggering fallback to fake.
        
        Returns dict with:
            {
                "counts": {...},
                "west_metrics": {...}
            }
        """
        if not self.use_camera_west or not self.yolo_source:
            return None

        try:
            result = self.yolo_source.read_west_counts()
            self.camera_ok = True
            self.camera_error_count = 0
            self.last_camera_ts = time.time()
            self.west_metrics = result.get("west_metrics")
            return result
        except Exception as e:
            self.camera_error_count += 1
            logger.warning(f"YOLO read error (attempt {self.camera_error_count}): {e}")

            if self.camera_error_count >= self.max_camera_errors:
                logger.warning(
                    f"Camera failed {self.max_camera_errors} times, falling back to fake WEST data"
                )
                self.camera_ok = False
                self.use_camera_west = False
            return None

    def get_counts(self) -> TrafficCounts:
        """
        Get counts: WEST from YOLO (if ok), N/E/S from fake.
        
        Implements automatic fallback: if camera fails, uses fake data
        and logs warning but doesn't crash.
        """
        # Always advance fake generator (for N/E/S and WEST backup)
        fake_counts = self.fake_gen.next_counts()

        # Try YOLO for WEST if enabled
        yolo_result = self._read_west_from_yolo() if self.use_camera_west else None

        # Build final counts
        final_counts = {}
        for road in Road:
            if road == Road.west_entry and yolo_result is not None:
                final_counts[road.value] = RoadVehicleCounts(**yolo_result.get("counts", {}))
            else:
                final_counts[road.value] = getattr(fake_counts, road.value)
                
        return TrafficCounts(**final_counts)

    def get_queue_metrics(self) -> Dict[Road, int]:
        """
        Get queue metrics. For now, return zeros (will be computed from counts by controller).
        This can be enhanced later with tracking logic.
        """
        return {road: 0 for road in Road}

    def get_west_metrics(self) -> Dict:
        """
        Get WEST-specific metrics from camera (if available).
        
        Returns dict with:
            {
                "waiting_count": int,
                "queue_length": int,
                "cleared_last_interval": int,
                "congestion_level": "LOW|MEDIUM|HIGH",
                "congestion_percent": int,
                "smoothed": bool,
                "roi_active": bool,
            }
        
        Or returns default zeros if camera not available.
        """
        if self.west_metrics:
            return self.west_metrics
        
        # Return defaults
        return {
            "waiting_count": 0,
            "queue_length": 0,
            "cleared_last_interval": 0,
            "congestion_level": "LOW",
            "congestion_percent": 0,
            "smoothed": self.smoothing_enabled,
            "roi_active": False,
        }

    def get_health_status(self) -> Dict:
        """
        Return health status of input sources.
        
        Returns:
            {
                "west_source": "camera" | "fake",
                "camera_ok": bool,
                "last_camera_ts": float (unix timestamp),
                "camera_error_count": int,
                "west_source_mode": "webcam" | "video" | None,
                "west_video_path": str | None,
            }
        """
        return {
            "west_source": "camera" if (self.use_camera_west and self.camera_ok) else "fake",
            "camera_ok": self.camera_ok,
            "last_camera_ts": self.last_camera_ts,
            "camera_error_count": self.camera_error_count if self.use_camera_west else 0,
            "west_source_mode": self.source_mode if self.use_camera_west else None,
            "west_video_path": self.video_path if (self.use_camera_west and self.source_mode == "video") else None,
        }

    def get_camera_frame_jpeg(self) -> Optional[bytes]:
        """
        Get latest annotated frame from WEST camera as JPEG bytes.
        
        Returns:
            JPEG bytes or None if camera disabled/unavailable
        """
        if not self.use_camera_west or not self.yolo_source:
            return None
        
        try:
            return self.yolo_source.get_latest_frame_jpeg()
        except Exception as e:
            logger.error(f"Error getting camera frame: {e}")
            return None

    def get_raw_camera_frame_jpeg(self) -> Optional[bytes]:
        """
        Get latest raw unannotated frame from WEST camera as JPEG bytes.
        
        Returns:
            JPEG bytes or None if camera disabled/unavailable
        """
        if not self.use_camera_west or not self.yolo_source:
            return None
        
        try:
            return self.yolo_source.get_latest_raw_frame_jpeg()
        except Exception as e:
            logger.error(f"Error getting raw camera frame: {e}")
            return None

    def get_camera_info(self) -> Dict:
        """
        Get detailed camera status including detections and fallback status.
        
        Returns:
            {
                "camera_ok": bool,
                "last_frame_ts": float,
                "detections": [{"cls_raw": str, "cls_mapped": str, "conf": float, "x1": int, ...}],
                "using_fake_fallback": bool,
                "vehicle_counts": {car, bike, bus, truck, lorry, auto},  # NEW: aggregated counts from detections
            }
        """
        if not self.use_camera_west or not self.yolo_source:
            return {
                "camera_ok": False,
                "last_frame_ts": 0.0,
                "detections": [],
                "using_fake_fallback": True,
                "vehicle_counts": {"car": 0, "bike": 0, "bus": 0, "truck": 0, "lorry": 0, "auto": 0},
            }
        
        try:
            status = self.yolo_source.get_status()
            status["using_fake_fallback"] = not self.camera_ok
            
            # NEW: Compute vehicle counts from detections
            vehicle_counts = {"car": 0, "bike": 0, "bus": 0, "truck": 0, "lorry": 0, "auto": 0}
            for detection in status.get("detections", []):
                cls_mapped = detection.get("cls_mapped", "unknown")
                if cls_mapped in vehicle_counts:
                    vehicle_counts[cls_mapped] += 1
            status["vehicle_counts"] = vehicle_counts
            
            return status
        except Exception as e:
            logger.error(f"Error getting camera info: {e}")
            return {
                "camera_ok": False,
                "last_frame_ts": 0.0,
                "detections": [],
                "using_fake_fallback": True,
            }

    def shutdown(self):
        """Cleanup resources (camera, etc)."""
        if self.yolo_source:
            try:
                self.yolo_source.stop()
            except Exception as e:
                logger.warning(f"Error shutting down YOLO: {e}")
