import asyncio
import sys
import os
import json
import logging
from typing import Dict, Optional, List, Set
from datetime import datetime
from uuid import uuid4
from dotenv import load_dotenv
import time

import cv2
import numpy as np

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from controller.state_models import (
    StatusResponse,
    EmergencyInfo,
    SignalState,
    DecisionInfo,
    Road,
    RoadMetricsSet,
    PredictionSet,
    PredictionMetrics,
    InputHealthInfo,
    WestCameraInfo,
    DetectionInfo,
    TrafficCounts,
    RoadVehicleCounts,
)
from controller.sumo_connector import SUMOConnector
from controller.traffic_controller import TrafficController
from controller.memory_store import MemoryStore
from controller.prediction import TrafficPredictor
from controller.data_provider import HybridProvider
from controller.road_provider import HybridProvider as RoadHybridProvider, FakeProvider, SumoProvider
from controller.accident_detector import AccidentDetector
from controller.fire_smoke_detector import FireSmokeDetector
from controller.mongo_sumo_injector import MongoSumoInjector
from controller.sumo_road_map import SUMO_ROADS
from db import mongo_client

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

app = FastAPI(title="Smart Traffic Backend (SUMO)", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# === WebSocket Connection Manager ===

class ConnectionManager:
    """Manages WebSocket connections and broadcasting"""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"Client connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"Client disconnected. Total clients: {len(self.active_connections)}")

    async def broadcast_json(self, data: dict):
        disconnected = []
        for connection in list(self.active_connections):
            try:
                await connection.send_json(data)
            except Exception as e:
                logger.debug(f"Error broadcasting to client: {e}")
                disconnected.append(connection)

        for connection in disconnected:
            self.disconnect(connection)

    def get_connection_count(self) -> int:
        return len(self.active_connections)


# === Pydantic Models ===

class ControlResponse(BaseModel):
    status: str
    message: Optional[str] = None


class ModeRequest(BaseModel):
    mode: str  # "AUTO" or "MANUAL"


class ModeResponse(BaseModel):
    mode: str
    manual_active: bool
    manual_command: Optional[str] = None
    remaining_seconds: int = 0


class ManualApplyRequest(BaseModel):
    command: str
    duration: int  # 10-120 seconds
    reason: Optional[str] = None
    alert_type: Optional[str] = None
    severity: Optional[str] = None


class ManualApplyResponse(BaseModel):
    status: str
    message: str
    command: str
    duration: int
    effective_phase: Optional[str] = None
    note: Optional[str] = None


class Alert(BaseModel):
    id: str
    timestamp: str
    severity: str  # LOW, MED, HIGH
    type: str      # ACCIDENT, EMERGENCY, CAMERA_DOWN, CONGESTION
    message: str
    roadId: str
    status: str    # ACTIVE, ACK, RESOLVED
    ackBy: Optional[str] = None
    ackAt: Optional[str] = None
    resolvedAt: Optional[str] = None


class AlertListResponse(BaseModel):
    active: List[Alert] = []
    recent: List[Alert] = []


class AlertAckRequest(BaseModel):
    ackBy: str


class QuickManualRequest(BaseModel):
    direction: str  # NS | EW | ALL_RED
    durationSec: int


# === Paths ===

BASE_DIR = os.path.dirname(__file__)
# MongoDB Injection Config
SUMO_USE_MONGO_INJECTION = os.getenv("SUMO_USE_MONGO_INJECTION", "true").lower() == "true"
SUMO_USE_STATIC_FLOWS = os.getenv("SUMO_USE_STATIC_FLOWS", "false").lower() == "true"

SUMO_CFG_ENV = os.getenv("SUMO_CFG_PATH", "sumo_configs/3junctions.sumocfg")
if not SUMO_USE_STATIC_FLOWS and "3junctions.sumocfg" in SUMO_CFG_ENV:
    # If using the 3junctions config but static flows are disabled, use the no-flows variant
    SUMO_CFG_ENV = SUMO_CFG_ENV.replace("3junctions.sumocfg", "3junctions_no_flows.sumocfg")
    
SUMO_CFG = os.path.normpath(os.path.join(BASE_DIR, SUMO_CFG_ENV))
METRICS_LOG_PATH = os.path.join(BASE_DIR, "data", "logs.jsonl")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "smart_traffic")
MONGO_COLL = os.getenv("MONGO_DETECTION_COLLECTION", "Detections_NOR-VE")

os.makedirs(os.path.dirname(METRICS_LOG_PATH), exist_ok=True)


def _resolve_local_path(path_value: str) -> str:
    if not path_value:
        return path_value
    if os.path.isabs(path_value):
        return path_value
    return os.path.normpath(os.path.join(BASE_DIR, path_value))


# === Environment Configuration ===

USE_CAMERA_WEST = os.getenv("USE_CAMERA_WEST", "false").lower() == "true"
WEST_CAMERA_INDEX = int(os.getenv("WEST_CAMERA_INDEX", "0"))
WEST_MODEL_PATH = _resolve_local_path(os.getenv("WEST_MODEL_PATH", "models/best.pt"))
WEST_CONF = float(os.getenv("WEST_CONF", "0.20"))
WEST_IOU = float(os.getenv("WEST_IOU", "0.45"))
WEST_IMGSZ = int(os.getenv("WEST_IMGSZ", "960"))
WEST_MAX_DET = int(os.getenv("WEST_MAX_DET", "100"))
WEST_USE_TRACKING = os.getenv("WEST_USE_TRACKING", "false").lower() == "true"
WEST_ROI = os.getenv("WEST_ROI", "")
WEST_SMOOTHING_ENABLED = os.getenv("WEST_SMOOTHING_ENABLED", "true").lower() == "true"
WEST_SMOOTHING_WINDOW = int(os.getenv("WEST_SMOOTHING_WINDOW", "5"))
WEST_RESIZE_WIDTH = int(os.getenv("WEST_RESIZE_WIDTH", "960"))

WEST_SOURCE_MODE = os.getenv("WEST_SOURCE_MODE", "webcam").lower()
WEST_VIDEO_PATH = os.getenv("WEST_VIDEO_PATH", "")
WEST_LOOP_VIDEO = os.getenv("WEST_LOOP_VIDEO", "false").lower() == "true"

# Accident model config
ACCIDENT_MODEL_ENABLED = os.getenv("ACCIDENT_MODEL_ENABLED", "true").lower() == "true"
ACCIDENT_MODEL_PATH = _resolve_local_path(
    os.getenv("ACCIDENT_MODEL_PATH", "models/accident_best.pt")
)
ACCIDENT_CONF_THRESHOLD = float(os.getenv("ACCIDENT_CONF_THRESHOLD", "0.50"))
ACCIDENT_CHECK_INTERVAL_SEC = float(os.getenv("ACCIDENT_CHECK_INTERVAL_SEC", "0.5"))
ACCIDENT_CONSECUTIVE_FRAMES = int(os.getenv("ACCIDENT_CONSECUTIVE_FRAMES", "1"))
ACCIDENT_MANUAL_COMMAND = os.getenv("ACCIDENT_MANUAL_COMMAND", "ALL_RED")
ACCIDENT_MANUAL_DURATION = int(os.getenv("ACCIDENT_MANUAL_DURATION", "30"))
ACCIDENT_ENTRY_POINT = os.getenv("ACCIDENT_ENTRY_POINT", "-W0")
ACCIDENT_ROAD_ID = os.getenv("ACCIDENT_ROAD_ID", "west")
ACCIDENT_TRIGGER_COOLDOWN_SEC = float(os.getenv("ACCIDENT_TRIGGER_COOLDOWN_SEC", "10.0"))

# Fire/Smoke model config
FIRE_SMOKE_MODEL_ENABLED = os.getenv("FIRE_SMOKE_MODEL_ENABLED", "true").lower() == "true"
FIRE_SMOKE_MODEL_PATH = _resolve_local_path(
    os.getenv("FIRE_SMOKE_MODEL_PATH", "models/fire_smoke_best.pt")
)
FIRE_SMOKE_CONF_THRESHOLD = float(os.getenv("FIRE_SMOKE_CONF_THRESHOLD", "0.25"))
FIRE_SMOKE_PASSIVE_CHECK_INTERVAL_SEC = float(os.getenv("FIRE_SMOKE_PASSIVE_CHECK_INTERVAL_SEC", "1.0"))
FIRE_SMOKE_EMERGENCY_CHECK_INTERVAL_SEC = float(os.getenv("FIRE_SMOKE_EMERGENCY_CHECK_INTERVAL_SEC", "0.25"))
FIRE_SMOKE_ALERT_LATCH_SEC = float(os.getenv("FIRE_SMOKE_ALERT_LATCH_SEC", "10.0"))
EMERGENCY_POPUP_REQUIRE_ACK = os.getenv("EMERGENCY_POPUP_REQUIRE_ACK", "true").lower() == "true"


# === Core components ===

memory_store = MemoryStore("data/memory.json")
sumo_connector = None
sumo_injector: Optional[MongoSumoInjector] = None
controller: Optional[TrafficController] = None
predictor = TrafficPredictor()
accident_detector: Optional[AccidentDetector] = None

from controller.fire_smoke_detector import FireSmokeDetector
fire_smoke_detector: Optional[FireSmokeDetector] = None


def _build_data_provider() -> HybridProvider:
    provider = HybridProvider(
        use_camera_west=USE_CAMERA_WEST,
        camera_index=WEST_CAMERA_INDEX,
        model_path=WEST_MODEL_PATH,
        conf=WEST_CONF,
        iou=WEST_IOU,
        imgsz=WEST_IMGSZ,
        max_det=WEST_MAX_DET,
        use_tracking=WEST_USE_TRACKING,
        roi_west=WEST_ROI,
        smoothing_enabled=WEST_SMOOTHING_ENABLED,
        smoothing_window=WEST_SMOOTHING_WINDOW,
        resize_width=WEST_RESIZE_WIDTH,
        source_mode=WEST_SOURCE_MODE,
        video_path=WEST_VIDEO_PATH if WEST_VIDEO_PATH else None,
        loop_video=WEST_LOOP_VIDEO,
    )
    source_info = f"mode={WEST_SOURCE_MODE}"
    if WEST_SOURCE_MODE == "video":
        source_info += f", video={WEST_VIDEO_PATH}, loop={WEST_LOOP_VIDEO}"
    else:
        source_info += f", cam={WEST_CAMERA_INDEX}"
    logger.info(
        f"Hybrid Provider initialized: USE_CAMERA_WEST={USE_CAMERA_WEST}, {source_info}, "
        f"model_path={WEST_MODEL_PATH}, conf={WEST_CONF}, roi={'set' if WEST_ROI else 'none'}, "
        f"smoothing={WEST_SMOOTHING_ENABLED}"
    )
    return provider


def _build_accident_detector() -> Optional[AccidentDetector]:
    if not ACCIDENT_MODEL_ENABLED:
        logger.info("[ACCIDENT] Accident detector disabled by .env")
        return None

    if not os.path.exists(ACCIDENT_MODEL_PATH):
        logger.warning(f"[ACCIDENT] Model file not found: {ACCIDENT_MODEL_PATH}")
        return None

    try:
        detector = AccidentDetector(
            model_path=ACCIDENT_MODEL_PATH,
            conf_threshold=ACCIDENT_CONF_THRESHOLD,
            consecutive_frames=ACCIDENT_CONSECUTIVE_FRAMES,
        )
        logger.info(
            f"[ACCIDENT] Detector loaded: path={ACCIDENT_MODEL_PATH}, "
            f"threshold={ACCIDENT_CONF_THRESHOLD}, consecutive={ACCIDENT_CONSECUTIVE_FRAMES}"
        )
        return detector
    except Exception as e:
        logger.error(f"[ACCIDENT] Failed to initialize detector: {e}", exc_info=True)
        return None

def _build_fire_smoke_detector() -> Optional[FireSmokeDetector]:
    if not FIRE_SMOKE_MODEL_ENABLED:
        logger.info("[FIRE_SMOKE] Fire/smoke detector disabled by .env")
        return None

    if not os.path.exists(FIRE_SMOKE_MODEL_PATH):
        logger.warning(f"[FIRE_SMOKE] Model file not found: {FIRE_SMOKE_MODEL_PATH}")
        return None

    try:
        detector = FireSmokeDetector(
            model_path=FIRE_SMOKE_MODEL_PATH,
            conf_threshold=FIRE_SMOKE_CONF_THRESHOLD
        )
        logger.info(f"[FIRE_SMOKE] Detector loaded: path={FIRE_SMOKE_MODEL_PATH}, threshold={FIRE_SMOKE_CONF_THRESHOLD}")
        return detector
    except Exception as e:
        logger.error(f"[FIRE_SMOKE] Failed to initialize detector: {e}", exc_info=True)
        return None

def _get_data_provider() -> HybridProvider:
    global data_provider
    if data_provider is None:
        data_provider = _build_data_provider()
    return data_provider


def _get_controller() -> TrafficController:
    global controller
    if controller is None:
        controller = TrafficController()
    return controller


data_provider: Optional[HybridProvider] = _build_data_provider()
accident_detector: Optional[AccidentDetector] = _build_accident_detector()
fire_smoke_detector: Optional[FireSmokeDetector] = _build_fire_smoke_detector()

_accident_task = None
accident_state = {
    "active": False,
    "confidence": 0.0,
    "label": "Non_Accident",
    "roadId": ACCIDENT_ROAD_ID,
    "entryPoint": ACCIDENT_ENTRY_POINT,
    "lastDetectedAt": None,
    "lastDetectedTs": 0.0
}

fire_smoke_state = {
    "checking": False,
    "fireDetected": False,
    "smokeDetected": False,
    "fireConfidence": 0.0,
    "smokeConfidence": 0.0,
    "boxes": [],
    "lastCheckedAt": None,
    "lastDetectedAt": None,
    "lastDetectedTs": 0.0
}

emergency_state = {
    "id": None,
    "popupActive": False,
    "requiresAck": True,
    "acknowledged": False,
    "accidentActive": False,
    "accidentConfidence": 0.0,
    "fireSmokeChecked": False,
    "fireDetected": False,
    "smokeDetected": False,
    "fireConfidence": 0.0,
    "smokeConfidence": 0.0,
    "emergencyLevel": "NORMAL",
    "message": "No emergency detected.",
    "roadId": ACCIDENT_ROAD_ID,
    "entryPoint": ACCIDENT_ENTRY_POINT,
    "lastDetectedAt": None
}

# Unified road provider
road_provider = None

# WebSocket manager
ws_manager = ConnectionManager()

# Alert storage
active_alerts: List[Alert] = []
alert_history: List[Alert] = []

_last_camera_alert_time: float = 0.0
_last_emergency_alert_time: float = 0.0
_camera_alert_cooldown_sec: float = 5.0
_emergency_alert_cooldown_sec: float = 2.0

# Accident runtime state
last_accident_check_time: float = 0.0
last_accident_trigger_time: float = 0.0
latest_accident_state: Dict = {
    "active": False,
    "confidence": 0.0,
    "label": "Non_Accident",
    "consecutive_hits": 0,
    "area": "west_camera_full_frame",
    "entryPoint": ACCIDENT_ENTRY_POINT,
    "roadId": ACCIDENT_ROAD_ID,
    "last_detected_at": None,
}

# Runtime state
simulation_active: bool = False
_sim_task: Optional[asyncio.Task] = None
_time_sec: int = 0
_current_status: Optional[StatusResponse] = None

# Manual override state
manual_mode: str = "AUTO"
manual_command: Optional[str] = None
manual_until: Optional[float] = None

MANUAL_COMMAND_TO_EFFECTIVE = {
    "NS_GREEN": "NS_GREEN",
    "EW_GREEN": "EW_GREEN",
    "ALL_RED": "ALL_RED",
    "N_ONLY": "NS_GREEN",
    "S_ONLY": "NS_GREEN",
    "E_ONLY": "EW_GREEN",
    "W_ONLY": "EW_GREEN",
    "BLOCK_N": "EW_GREEN",
    "BLOCK_S": "EW_GREEN",
    "BLOCK_E": "NS_GREEN",
    "BLOCK_W": "NS_GREEN",
    "BLOCK_NS": "EW_GREEN",
    "BLOCK_EW": "NS_GREEN",
    "CLEAR_N": "NS_GREEN",
    "CLEAR_S": "NS_GREEN",
    "CLEAR_E": "EW_GREEN",
    "CLEAR_W": "EW_GREEN",
}
VALID_MANUAL_COMMANDS = set(MANUAL_COMMAND_TO_EFFECTIVE.keys())


def _get_effective_manual_command(command: Optional[str]) -> Optional[str]:
    if command is None:
        return None
    return MANUAL_COMMAND_TO_EFFECTIVE.get(command)


def _describe_manual_command(command: Optional[str]) -> str:
    labels = {
        "NS_GREEN": "North + South flow",
        "EW_GREEN": "East + West flow",
        "ALL_RED": "All red stop",
        "N_ONLY": "North priority",
        "S_ONLY": "South priority",
        "E_ONLY": "East priority",
        "W_ONLY": "West priority",
        "BLOCK_N": "Block North",
        "BLOCK_S": "Block South",
        "BLOCK_E": "Block East",
        "BLOCK_W": "Block West",
        "BLOCK_NS": "Block North + South",
        "BLOCK_EW": "Block East + West",
        "CLEAR_N": "Clear North",
        "CLEAR_S": "Clear South",
        "CLEAR_E": "Clear East",
        "CLEAR_W": "Clear West",
    }
    return labels.get(command, command or "none")


def _get_manual_remaining(current_time: Optional[float] = None) -> int:
    if current_time is None:
        current_time = time.time()
    if manual_mode == "MANUAL" and manual_until is not None:
        return max(0, int(manual_until - current_time))
    return 0


def _cancel_manual_state() -> None:
    global manual_mode, manual_command, manual_until
    manual_mode = "AUTO"
    manual_command = None
    manual_until = None


def _manual_expired(current_time: Optional[float] = None) -> bool:
    if current_time is None:
        current_time = time.time()
    return manual_mode == "MANUAL" and manual_until is not None and current_time >= manual_until


def _manual_command_display_group(command: Optional[str]):
    mapping = {
        "NS_GREEN": [Road.j1_north_entry, Road.j8_north_entry, Road.j8_south_entry],
        "EW_GREEN": [Road.j8_east_entry, Road.west_entry],
        "N_ONLY": [Road.j1_north_entry, Road.j8_north_entry],
        "E_ONLY": [Road.j8_east_entry],
        "S_ONLY": [Road.j8_south_entry],
        "W_ONLY": [Road.west_entry],
        "CLEAR_N": [Road.j1_north_entry, Road.j8_north_entry],
        "CLEAR_E": [Road.j8_east_entry],
        "CLEAR_S": [Road.j8_south_entry],
        "CLEAR_W": [Road.west_entry],
        "BLOCK_N": [Road.j8_east_entry, Road.west_entry, Road.j8_south_entry],
        "BLOCK_S": [Road.j8_east_entry, Road.west_entry, Road.j1_north_entry, Road.j8_north_entry],
        "BLOCK_NS": [Road.j8_east_entry, Road.west_entry],
        "BLOCK_E": [Road.j1_north_entry, Road.j8_north_entry, Road.j8_south_entry, Road.west_entry],
        "BLOCK_W": [Road.j1_north_entry, Road.j8_north_entry, Road.j8_south_entry, Road.j8_east_entry],
        "BLOCK_EW": [Road.j1_north_entry, Road.j8_north_entry, Road.j8_south_entry],
    }
    return mapping.get(command, None)


def _apply_manual_phase(current_time: float, time_sec: int) -> DecisionInfo:
    ctrl = _get_controller()
    if ctrl.remaining_green > 0:
        ctrl.remaining_green -= 1
    ctrl._since_last_decision += 1

    remaining = _get_manual_remaining(current_time)
    if manual_command == "ALL_RED":
        ctrl.remaining_green = max(1, remaining)
        ctrl._since_last_decision = 0
        return DecisionInfo(method="manual", reason=f"Manual ALL_RED ({remaining}s remaining)")

    group = _manual_command_display_group(manual_command) or [ctrl.current_green]

    needs_switch = (
        ctrl.current_green not in group
        or ctrl.remaining_green <= 0
        or ctrl._since_last_decision >= ctrl.decision_cycle
    )

    if len(group) == 1:
        ctrl.current_green = group[0]
        ctrl.remaining_green = max(1, remaining)
        ctrl._since_last_decision = 0
    elif needs_switch:
        if ctrl.current_green == group[0]:
            ctrl.current_green = group[1]
        else:
            ctrl.current_green = group[0]
        ctrl.remaining_green = min(30, max(1, remaining))
        ctrl._since_last_decision = 0

    return DecisionInfo(
        method="manual",
        reason=f"Manual {manual_command}: {ctrl.current_green.value} ({remaining}s remaining)",
    )


def _log_metrics(time_sec: int, metrics: RoadMetricsSet, signal_state: SignalState, predictions: Optional[Dict] = None):
    try:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "simulation_time": time_sec,
            "metrics": metrics.dict(),
            "signal": {
                "green_road": signal_state.greenRoad.value,
                "remaining_seconds": signal_state.remaining,
            },
        }

        if predictions:
            log_entry["predictions"] = {}
            for road, pred in predictions.items():
                log_entry["predictions"][road.value] = {
                    "queue_trend": pred.get("queue_trend", "stable"),
                    "heavy_traffic_probability": pred.get("heavy_traffic_probability", 0.0),
                    "congestion_level": pred.get("congestion_level", "LOW"),
                    "predicted_eta_clear_seconds": pred.get("predicted_eta_clear_seconds", 0),
                }

        with open(METRICS_LOG_PATH, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        print(f"Warning: Could not log metrics: {e}")


def _decode_jpeg_to_bgr(frame_bytes: bytes):
    try:
        arr = np.frombuffer(frame_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        return frame
    except Exception as e:
        logger.warning(f"[ACCIDENT] Failed to decode JPEG frame: {e}")
        return None


def _build_accident_payload() -> Dict:
    return {
        "active": latest_accident_state.get("active", False),
        "confidence": latest_accident_state.get("confidence", 0.0),
        "label": latest_accident_state.get("label", "Non_Accident"),
        "consecutive_hits": latest_accident_state.get("consecutive_hits", 0),
        "area": latest_accident_state.get("area", "west_camera_full_frame"),
        "entryPoint": latest_accident_state.get("entryPoint", ACCIDENT_ENTRY_POINT),
        "roadId": latest_accident_state.get("roadId", ACCIDENT_ROAD_ID),
        "last_detected_at": latest_accident_state.get("last_detected_at"),
    }


async def _insert_accident_record_to_mongo(confidence: float, area: str):
    print("[ACCIDENT][MONGO] insert requested")
    print(
        f"[ACCIDENT][MONGO] configured={mongo_client.is_configured()} connected={mongo_client.connected}"
    )

    if not mongo_client.is_configured() or not mongo_client.connected:
        print("[ACCIDENT][MONGO] skipped because MongoDB is not connected/configured")
        return

    try:
        record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "type": "accident",
            "data": {
                "entryPoint": ACCIDENT_ENTRY_POINT,
                "roadId": ACCIDENT_ROAD_ID,
                "source": "west_camera_classifier",
                "confidence": confidence,
                "detectedArea": area,
                "manualCommand": ACCIDENT_MANUAL_COMMAND,
                "manualDuration": ACCIDENT_MANUAL_DURATION,
                "status": "ACTIVE",
            },
        }

        print(f"[ACCIDENT][MONGO] record={record}")
        success = await mongo_client.insert_detection(record)
        print(f"[ACCIDENT][MONGO] insert success={success}")
    except Exception as e:
        print(f"[ACCIDENT][MONGO] exception={type(e).__name__}: {e}")
        logger.error(f"[ACCIDENT][MONGO] Failed to save accident record: {e}", exc_info=True)

async def _trigger_accident_workflow(confidence: float, area: str):
    global manual_mode, manual_command, manual_until, last_accident_trigger_time

    now_ts = time.time()
    if (now_ts - last_accident_trigger_time) < ACCIDENT_TRIGGER_COOLDOWN_SEC:
        return

    last_accident_trigger_time = now_ts

    latest_accident_state["active"] = True
    latest_accident_state["confidence"] = confidence
    latest_accident_state["area"] = area
    latest_accident_state["entryPoint"] = ACCIDENT_ENTRY_POINT
    latest_accident_state["roadId"] = ACCIDENT_ROAD_ID
    latest_accident_state["last_detected_at"] = datetime.utcnow().isoformat()

    alert = _create_alert(
        "HIGH",
        "ACCIDENT",
        f"Accident detected on WEST road (confidence={confidence:.2f})",
        "west",
    )
    await _broadcast_event("ALERT_CREATED", alert.dict())

    manual_mode = "MANUAL"
    manual_command = ACCIDENT_MANUAL_COMMAND
    manual_until = now_ts + ACCIDENT_MANUAL_DURATION

    _log_manual_event(
        "manual_apply",
        "MANUAL",
        ACCIDENT_MANUAL_COMMAND,
        ACCIDENT_MANUAL_DURATION,
        "accident_auto_trigger",
    )

    await _broadcast_event(
        "MODE_CHANGED",
        {
            "mode": manual_mode,
            "manual_active": True,
            "manual_command": manual_command,
            "remaining_seconds": ACCIDENT_MANUAL_DURATION,
            "reason": "accident_auto_trigger",
        },
    )

    await _broadcast_event(
        "ACCIDENT_DETECTED",
        {
            "confidence": confidence,
            "area": area,
            "entryPoint": ACCIDENT_ENTRY_POINT,
            "roadId": ACCIDENT_ROAD_ID,
            "manualCommand": ACCIDENT_MANUAL_COMMAND,
            "manualDuration": ACCIDENT_MANUAL_DURATION,
        },
    )

    await _insert_accident_record_to_mongo(confidence, area)


# === Status / Basic API ===

@app.get("/api/status", response_model=StatusResponse)
async def get_status():
    global _current_status
    try:
        if _current_status is None:
            empty_counts = TrafficCounts(
                west_entry=RoadVehicleCounts(),
                j1_north_entry=RoadVehicleCounts(),
                j8_north_entry=RoadVehicleCounts(),
                j8_east_entry=RoadVehicleCounts(),
                j8_south_entry=RoadVehicleCounts(),
            )
            provider = _get_data_provider()
            input_health = InputHealthInfo(**provider.get_health_status())
            camera_info_dict = provider.get_camera_info()
            west_camera = WestCameraInfo(
                camera_ok=camera_info_dict["camera_ok"],
                last_frame_ts=camera_info_dict["last_frame_ts"],
                detections=[DetectionInfo(**d) for d in camera_info_dict["detections"]],
                using_fake_fallback=camera_info_dict["using_fake_fallback"],
            )
            _current_status = StatusResponse(
                time=_time_sec,
                counts=empty_counts,
                queues={
                    Road.west_entry: 0,
                    Road.j1_north_entry: 0,
                    Road.j8_north_entry: 0,
                    Road.j8_east_entry: 0,
                    Road.j8_south_entry: 0
                },
                signal=SignalState(
                    greenRoad=(controller.current_green if controller else Road.j8_south_entry),
                    remaining=(controller.remaining_green if controller else 0),
                ),
                emergency=EmergencyInfo(active=False, road=None),
                decision=DecisionInfo(method="idle", reason="simulation not started"),
                inputs=input_health,
                west_camera=west_camera,
            )
        return _current_status
    except Exception as e:
        print(f"[API ERROR] /api/status failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))



@app.get("/api/memory/summary")
async def memory_summary():
    return memory_store.summary()


@app.get("/api/west/camera/frame")
async def get_west_camera_frame():
    frame_bytes = _get_data_provider().get_camera_frame_jpeg()
    if frame_bytes is None:
        return Response(
            content=b"",
            status_code=503,
            media_type="application/json",
            headers={"X-Camera-Status": "unavailable"},
        )
    return Response(
        content=frame_bytes,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


@app.get("/api/west/camera/status")
async def get_west_camera_status():
    return _get_data_provider().get_camera_info()


@app.get("/api/accident/status")
async def get_accident_status():
    return _build_accident_payload()


# === Alert Helpers ===

def _create_alert(severity: str, alert_type: str, message: str, road_id: str) -> Alert:
    alert = Alert(
        id=str(uuid4()),
        timestamp=datetime.utcnow().isoformat(),
        severity=severity,
        type=alert_type,
        message=message,
        roadId=road_id,
        status="ACTIVE",
    )
    active_alerts.insert(0, alert)
    logger.info(f"[ALERT] Created {alert_type}: {message} (severity={severity})")
    return alert


def _find_alert(alert_id: str) -> Optional[Alert]:
    for alert in active_alerts:
        if alert.id == alert_id:
            return alert
    return None


def _ack_alert(alert_id: str, ack_by: str) -> Optional[Alert]:
    alert = _find_alert(alert_id)
    if alert and alert.status == "ACTIVE":
        alert.status = "ACK"
        alert.ackBy = ack_by
        alert.ackAt = datetime.utcnow().isoformat()
        return alert
    return None


def _resolve_alert(alert_id: str) -> Optional[Alert]:
    alert = _find_alert(alert_id)
    if alert and alert.status in ["ACTIVE", "ACK"]:
        alert.status = "RESOLVED"
        alert.resolvedAt = datetime.utcnow().isoformat()
        active_alerts.remove(alert)
        alert_history.insert(0, alert)
        if len(alert_history) > 100:
            alert_history.pop()
        return alert
    return None


async def _broadcast_event(event_name: str, data: dict):
    event_msg = {
        "event": event_name,
        "timestamp": datetime.utcnow().isoformat(),
        "data": data,
    }
    await ws_manager.broadcast_json(event_msg)


# === Alert REST ===

@app.get("/api/alerts", response_model=AlertListResponse)
async def get_alerts():
    return AlertListResponse(active=active_alerts, recent=alert_history[:20])


@app.post("/api/alerts/fake", response_model=Alert)
async def create_fake_alert(
    roadId: str = "west",
    severity: str = "MED",
    alert_type: str = "ACCIDENT",
    message: str = "Test alert",
):
    valid_roads = ["west_entry", "j1_north_entry", "j8_north_entry", "j8_east_entry", "j8_south_entry"]
    if roadId not in valid_roads:
        raise HTTPException(status_code=400, detail=f"roadId must be one of {valid_roads}")

    valid_severities = ["LOW", "MED", "HIGH"]
    if severity not in valid_severities:
        raise HTTPException(status_code=400, detail=f"severity must be one of {valid_severities}")

    alert = _create_alert(severity, alert_type, message, roadId)
    await _broadcast_event("ALERT_CREATED", alert.dict())
    return alert


@app.post("/api/alerts/{alert_id}/ack", response_model=Alert)
async def ack_alert(alert_id: str, request: AlertAckRequest):
    alert = _ack_alert(alert_id, request.ackBy)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found or already acked/resolved")
    await _broadcast_event("ALERT_ACKED", alert.dict())
    return alert


@app.post("/api/alerts/{alert_id}/resolve", response_model=Alert)
async def resolve_alert(alert_id: str):
    alert = _resolve_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found or already resolved")
    await _broadcast_event("ALERT_RESOLVED", alert.dict())
    return alert


# === Manual Control API ===

@app.get("/api/control/mode", response_model=ModeResponse)
async def get_control_mode():
    current_time = time.time()
    remaining = _get_manual_remaining(current_time)
    return ModeResponse(
        mode=manual_mode,
        manual_active=(manual_mode == "MANUAL"),
        manual_command=manual_command,
        remaining_seconds=remaining,
    )


@app.post("/api/control/mode", response_model=ModeResponse)
async def set_control_mode(request: ModeRequest):
    current_time = time.time()

    if request.mode not in ["AUTO", "MANUAL"]:
        raise HTTPException(status_code=400, detail="Mode must be 'AUTO' or 'MANUAL'")

    global manual_mode, manual_command, manual_until
    if request.mode == "AUTO":
        _cancel_manual_state()
        _log_manual_event("mode_change", "AUTO", None, 0, "user_request")
    else:
        manual_mode = "MANUAL"
        manual_command = None
        manual_until = None
        _log_manual_event("mode_change", "MANUAL", None, 0, "user_request")

    mode_data = {
        "mode": manual_mode,
        "manual_active": (manual_mode == "MANUAL"),
        "manual_command": manual_command,
        "remaining_seconds": _get_manual_remaining(current_time),
    }
    await _broadcast_event("MODE_CHANGED", mode_data)

    remaining = _get_manual_remaining(current_time)
    return ModeResponse(
        mode=manual_mode,
        manual_active=(manual_mode == "MANUAL"),
        manual_command=manual_command,
        remaining_seconds=remaining,
    )


@app.post("/api/control/manual/apply", response_model=ManualApplyResponse)
async def apply_manual_control(request: ManualApplyRequest):
    current_time = time.time()

    if manual_mode != "MANUAL":
        raise HTTPException(
            status_code=409,
            detail="Not in MANUAL mode. Switch to MANUAL first via /api/control/mode",
        )

    valid_commands = ["NS_GREEN", "EW_GREEN", "ALL_RED"]
    if request.command not in valid_commands:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid command. Must be one of: {', '.join(valid_commands)}",
        )

    if not (10 <= request.duration <= 120):
        raise HTTPException(
            status_code=400,
            detail="Duration must be between 10 and 120 seconds",
        )

    global manual_command, manual_until
    manual_command = request.command
    manual_until = current_time + request.duration
    _log_manual_event("manual_apply", "MANUAL", request.command, request.duration, "user_request")

    await _broadcast_event(
        "MANUAL_APPLIED",
        {
            "command": request.command,
            "duration": request.duration,
            "until_ts": datetime.utcnow().isoformat(),
        },
    )
    await _broadcast_event(
        "MODE_CHANGED",
        {
            "mode": manual_mode,
            "manual_active": True,
            "manual_command": request.command,
            "remaining_seconds": request.duration,
        },
    )

    return ManualApplyResponse(
        status="success",
        message=f"Manual control applied: {request.command} for {request.duration}s",
        command=request.command,
        duration=request.duration,
    )


@app.post("/api/control/manual/cancel", response_model=ControlResponse)
async def cancel_manual_control():
    if manual_mode != "MANUAL":
        return ControlResponse(status="info", message="Not in manual mode")

    _cancel_manual_state()
    _log_manual_event("manual_cancel", "AUTO", None, 0, "user_request")

    await _broadcast_event(
        "MODE_CHANGED",
        {
            "mode": "AUTO",
            "manual_active": False,
            "manual_command": None,
            "remaining_seconds": 0,
        },
    )

    return ControlResponse(status="success", message="Manual control cancelled, returned to AUTO mode")


@app.post("/api/control/manual/quick", response_model=ManualApplyResponse)
async def quick_manual_control(request: QuickManualRequest):
    current_time = time.time()

    direction_map = {
        "NS": "NS_GREEN",
        "EW": "EW_GREEN",
        "ALL_RED": "ALL_RED",
    }

    if request.direction not in direction_map:
        raise HTTPException(
            status_code=400,
            detail="direction must be one of: NS, EW, ALL_RED",
        )

    if not (10 <= request.durationSec <= 120):
        raise HTTPException(
            status_code=400,
            detail="durationSec must be between 10 and 120 seconds",
        )

    global manual_mode, manual_command, manual_until

    manual_mode = "MANUAL"
    command = direction_map[request.direction]
    manual_command = command
    manual_until = current_time + request.durationSec
    _log_manual_event("manual_apply", "MANUAL", command, request.durationSec, "quick_control")

    await _broadcast_event(
        "MANUAL_APPLIED",
        {
            "command": command,
            "duration": request.durationSec,
            "until_ts": datetime.utcnow().isoformat(),
        },
    )
    await _broadcast_event(
        "MODE_CHANGED",
        {
            "mode": "MANUAL",
            "manual_active": True,
            "manual_command": command,
            "remaining_seconds": request.durationSec,
        },
    )

    return ManualApplyResponse(
        status="success",
        message=f"Quick control applied: {request.direction} for {request.durationSec}s",
        command=command,
        duration=request.durationSec,
    )


def _log_manual_event(event_type: str, mode: str, command: Optional[str], duration: int, reason: str):
    try:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "simulation_time": _time_sec,
            "event_type": event_type,
            "mode": mode,
            "command": command,
            "duration": duration,
            "reason": reason,
        }

        with open(METRICS_LOG_PATH, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        print(f"Warning: Could not log manual event: {e}")


async def _insert_vehicle_counts_to_mongo(time_sec: int, counts: TrafficCounts):
    print(f"[MONGO FUNC] _insert_vehicle_counts_to_mongo executing at time={time_sec}")
    is_config = mongo_client.is_configured()
    is_connected = mongo_client.connected
    print(f"[MONGO FUNC] Configuration check: is_configured={is_config}, connected={is_connected}")

    if not is_config or not is_connected:
        print(f"[MONGO FUNC] ✗ SKIPPING insertion: is_configured={is_config}, connected={is_connected}")
        return

    try:
        road_to_entry_point = {
            Road.west_entry: "west_entry",
            Road.j1_north_entry: "j1_north_entry",
            Road.j8_north_entry: "j8_north_entry",
            Road.j8_east_entry: "j8_east_entry",
            Road.j8_south_entry: "j8_south_entry",
        }

        for road, entry_point in road_to_entry_point.items():
            road_counts = getattr(counts, road.value)
            print(
                f"[MONGO FUNC] Road {entry_point}: bike={road_counts.bike}, bus={road_counts.bus}, "
                f"lorry={road_counts.lorry}, car={road_counts.car}, truck={road_counts.truck}, auto={road_counts.auto}"
            )

            vehicles = []
            for vehicle_type in ["bike", "bus", "lorry", "car", "truck", "auto"]:
                count = getattr(road_counts, vehicle_type, 0)
                vehicles.append({"type": vehicle_type, "count": count})

            record = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "type": "normal_vehicle",
                "data": {
                    "entryPoint": entry_point,
                    "vehicles": vehicles,
                },
            }

            print(
                f"[MONGO FUNC] About to insert {entry_point} with "
                f"{len([v for v in vehicles if v['count'] > 0])} non-zero vehicle types"
            )

            success = await mongo_client.insert_detection(record)
            if success:
                logger.debug(
                    f"[MONGO] Inserted {entry_point} counts: "
                    f"{len([v for v in vehicles if v['count'] > 0])} vehicle types"
                )
            else:
                print(f"[MONGO FUNC] ✗ insert_detection() returned False for {entry_point}")

    except Exception as e:
        print(f"[MONGO FUNC] ✗ EXCEPTION in _insert_vehicle_counts_to_mongo: {type(e).__name__}: {e}")
        logger.error(f"[MONGO] Error inserting vehicle counts: {e}", exc_info=True)


# === SUMO Metadata endpoints ===

@app.get("/api/sumo/roads")
async def get_sumo_roads():
    """Return the dynamic road mapping for the current network"""
    return [
        {"roadId": rid, **data}
        for rid, data in SUMO_ROADS.items()
    ]



@app.get("/api/sumo/injected-vehicles")
async def get_injected_vehicles():
    """Stub for getting recently injected vehicle stats if needed"""
    return {"status": "ok", "message": "Mongo injection is active"}

@app.get("/api/traffic/latest")
async def get_traffic_latest():
    """Return the latest traffic counts"""
    if not _current_status:
        raise HTTPException(status_code=404, detail="Traffic data not available yet")
    return _current_status.counts

# === Control endpoints ===

@app.post("/api/control/start", response_model=ControlResponse)
async def start_simulation():
    global simulation_active, _sim_task, sumo_connector, road_provider, data_provider, controller

    if simulation_active:
        return ControlResponse(status="already_running")

    try:
        print("[APP DEBUG] start_simulation() - checking MongoDB configuration...")
        is_mongo_configured = mongo_client.is_configured()
        print(f"[APP DEBUG] mongo_client.is_configured() returned: {is_mongo_configured}")

        logger.info(
    f"[MONGO STATUS] configured={mongo_client.is_configured()} connected={mongo_client.connected}"
)

        if is_mongo_configured:
            print("[APP DEBUG] MongoDB is_configured=True, calling connect()...")
            mongo_connected = await mongo_client.connect()
            print(f"[APP DEBUG] Mongo configured={mongo_client.is_configured()} connected={mongo_client.connected}")
            print(f"[APP DEBUG] mongo_client.connect() returned: {mongo_connected}")
            if mongo_connected:
                print(f"[APP DEBUG] ✓ MongoDB connected successfully: {mongo_client.db_name}.{mongo_client.collection_name}")
                logger.info("[INIT] MongoDB connected successfully")
            else:
                print("[APP DEBUG] ✗ MongoDB connect failed")
                logger.warning("[INIT] MongoDB not available, continuing without database logging")
        else:
            print("[APP DEBUG] ✗ MongoDB not configured, will skip MongoDB logging")
            logger.info("[INIT] MongoDB not configured, skipping connection")

        data_provider = _build_data_provider()
        road_provider = None
        controller = _get_controller()

        sumo_connector = SUMOConnector(SUMO_CFG, use_gui=True)
        sumo_connector.connect()

        # Initialize Injector if enabled
        global sumo_injector
        if SUMO_USE_MONGO_INJECTION:
            logger.info(f"[INIT] Initializing MongoSumoInjector: {MONGO_URI}")
            sumo_injector = MongoSumoInjector(MONGO_URI, MONGO_DB, MONGO_COLL)

        simulation_active = True
        _sim_task = asyncio.create_task(_run_loop())
        return ControlResponse(status="started", message=f"SUMO simulation started with GUI using {SUMO_CFG_ENV}")
    except Exception as e:
        return ControlResponse(status="error", message=f"Failed to start SUMO: {str(e)}")


@app.post("/api/control/stop", response_model=ControlResponse)
async def stop_simulation():
    global simulation_active, _sim_task, sumo_connector, road_provider, data_provider

    simulation_active = False

    if _sim_task:
        _sim_task.cancel()
        _sim_task = None

    if sumo_connector:
        sumo_connector.disconnect()
        sumo_connector = None

    road_provider = None

    # We purposefully do not shut down data_provider so surveillance can continue.
    # try:
    #     if data_provider is not None:
    #         data_provider.shutdown()
    #         data_provider = None
    # except Exception as e:
    #     logger.warning(f"Error shutting down data provider: {e}")

    try:
        print("[APP DEBUG] Disconnecting MongoDB...")
        await mongo_client.disconnect()
        print("[APP DEBUG] MongoDB disconnected")
        logger.info("[SHUTDOWN] MongoDB disconnected")
    except Exception as e:
        print(f"[APP DEBUG] Error disconnecting MongoDB: {e}")
        logger.warning(f"Error disconnecting MongoDB: {e}")

    return ControlResponse(status="stopped", message="SUMO simulation stopped")


# === Analytics endpoints ===

@app.get("/api/analytics/summary")
async def get_analytics_summary():
    if not mongo_client.is_configured():
        return {"error": "MongoDB not configured"}

    try:
        summary = await mongo_client.get_analytics_summary()
        return summary
    except Exception as e:
        logger.error(f"Analytics summary error: {e}")
        return {"error": str(e)}


@app.get("/api/analytics/by-road")
async def get_analytics_by_road():
    if not mongo_client.is_configured():
        return {"error": "MongoDB not configured"}

    try:
        road_data = await mongo_client.get_analytics_by_road()
        return road_data
    except Exception as e:
        logger.error(f"Analytics by road error: {e}")
        return {"error": str(e)}


@app.get("/api/analytics/by-vehicle-type")
async def get_analytics_by_vehicle_type():
    if not mongo_client.is_configured():
        return {"error": "MongoDB not configured"}

    try:
        vehicle_data = await mongo_client.get_analytics_by_vehicle_type()
        return vehicle_data
    except Exception as e:
        logger.error(f"Analytics by vehicle type error: {e}")
        return {"error": str(e)}


@app.get("/api/analytics/trend")
async def get_analytics_trend(minutes: int = 60):
    if not mongo_client.is_configured():
        return [{"error": "MongoDB not configured"}]

    try:
        trend_data = await mongo_client.get_analytics_trend(minutes)
        return trend_data
    except Exception as e:
        logger.error(f"Analytics trend error: {e}")
        return [{"error": str(e)}]


# === WebSocket ===

@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                continue
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.debug(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket)


def _convert_predictions_to_prediction_set(predictions: Optional[Dict]) -> PredictionSet:
    if not predictions:
        return PredictionSet()

    def to_metrics(pred_dict: dict) -> PredictionMetrics:
        return PredictionMetrics(
            queue_trend=pred_dict.get("queue_trend", "stable"),
            arrivals_10s=pred_dict.get("arrivals_10s", 0.0),
            arrivals_30s=pred_dict.get("arrivals_30s", 0.0),
            heavy_traffic_probability=pred_dict.get("heavy_traffic_probability", 0.0),
            congestion_level=pred_dict.get("congestion_level", "LOW"),
            predicted_eta_clear_seconds=pred_dict.get("predicted_eta_clear_seconds", 0),
        )

    return PredictionSet(
        **{road.value: to_metrics(predictions.get(road, {})) for road in Road}
    )


async def _broadcast_update(status: StatusResponse):
    base_status = status.dict()
    base_status["accident"] = _build_accident_payload()
    base_status["surveillance_emergency"] = emergency_state
    await ws_manager.broadcast_json(base_status)


# === Main simulation loop ===

async def _run_loop():
    global _time_sec, _current_status, simulation_active, sumo_connector, road_provider
    global manual_mode, manual_command, manual_until
    global last_accident_check_time

    ctrl = _get_controller()
    provider = _get_data_provider()

    ctrl.reset()
    predictor.reset()
    _time_sec = 0

    try:
        global road_provider
        if road_provider is None:
            # Use SUMO as data source if we have static flows enabled
            if os.getenv("SUMO_USE_STATIC_FLOWS", "false").lower() == "true":
                road_provider = SumoProvider(sumo_connector)
                logger.info("[INIT] Road provider: SUMO (Simulation-only mode)")
            else:
                fake_provider = FakeProvider(data_provider.fake_gen)
                yolo_source = data_provider.yolo_source if USE_CAMERA_WEST else None
                road_provider = RoadHybridProvider(fake_provider, yolo_source)
                logger.info(f"[INIT] Road provider: HYBRID (Camera={USE_CAMERA_WEST}, Fake={not USE_CAMERA_WEST})")

        while simulation_active and sumo_connector.is_running():
            current_real_time = time.time()

            # 1) Step SUMO
            sumo_connector.step()

            # 2) Get vehicle counts
            road_counts_dict = road_provider.get_counts()
            metadata = road_provider.get_metadata()

            # Dynamic build
            counts_kwargs = {}
            for road in Road:
                counts_kwargs[road.value] = RoadVehicleCounts(**road_counts_dict.get(road.value, {}))
            counts = TrafficCounts(**counts_kwargs)

            # 2.5) Inject from Mongo if enabled
            if SUMO_USE_MONGO_INJECTION and sumo_injector:
                try:
                    sumo_injector.inject_pending_vehicles()
                except Exception as e:
                    logger.error(f"[INJECTOR] Error during injection step: {e}")

            # Insert vehicle counts to Mongo (logging current state)
            try:
                await _insert_vehicle_counts_to_mongo(_time_sec, counts)
            except Exception as e:
                logger.error(f"[MONGO] Failed to schedule counts insert: {e}")

            west_source = metadata.get("west_source", "fake")

            if _time_sec % 2 == 0:
                west_total = sum(counts.west_entry.dict().values())
                logger.info(
                    f"[WEST INPUT] t={_time_sec}, using_camera={metadata.get('camera_ok', False)}, "
                    f"west_source={west_source}, west_counts={counts.west_entry.dict()}, total={west_total}"
                )

            emergency = sumo_connector.detect_emergency()

            # 2.6) Accident detection from WEST camera frame is now handled by independent background task.

            # 3) Update tracking
            sumo_connector._update_vehicle_tracking()

            # 4) Compute queues
            queues = controller.compute_queues(counts)

            # 5) Compute metrics
            metrics = sumo_connector.compute_metrics()

            # 6) Predictions
            predictions = predictor.predict(metrics)

            # 6.5) Auto alerts
            current_real_time_for_alerts = time.time()

            camera_ok = data_provider.get_health_status().get("camera_ok", True)
            if not camera_ok and (current_real_time_for_alerts - _last_camera_alert_time) > _camera_alert_cooldown_sec:
                try:
                    _create_alert("HIGH", "CAMERA_DOWN", "WEST camera offline, using fallback", "west")
                    await _broadcast_event("ALERT_CREATED", active_alerts[0].dict())
                    globals()["_last_camera_alert_time"] = current_real_time_for_alerts
                except Exception as e:
                    logger.warning(f"Failed to create camera alert: {e}")

            if emergency.active and (current_real_time_for_alerts - _last_emergency_alert_time) > _emergency_alert_cooldown_sec:
                try:
                    emergency_road = emergency.road.value if emergency.road else "unknown"
                    _create_alert("HIGH", "EMERGENCY", f"Emergency vehicle detected on {emergency_road} road", emergency_road)
                    await _broadcast_event("ALERT_CREATED", active_alerts[0].dict())
                    globals()["_last_emergency_alert_time"] = current_real_time_for_alerts
                except Exception as e:
                    logger.warning(f"Failed to create emergency alert: {e}")

            # 7) Priority: Emergency > Manual > AUTO
            if emergency.active and manual_mode == "MANUAL":
                _cancel_manual_state()
                _log_manual_event("emergency_interrupt", "AUTO", None, 0, "emergency_override")

            if emergency.active:
                decision_info = ctrl.tick_and_decide(
                    time_sec=_time_sec,
                    counts=counts,
                    queues=queues,
                    emergency=emergency,
                )
            elif manual_mode == "MANUAL":
                if _manual_expired(current_real_time):
                    _cancel_manual_state()
                    _log_manual_event("manual_expire", "AUTO", None, 0, "duration_expired")
                    decision_info = ctrl.tick_and_decide(
                        time_sec=_time_sec,
                        counts=counts,
                        queues=queues,
                        emergency=emergency,
                    )
                else:
                    decision_info = _apply_manual_phase(current_real_time, _time_sec)
            else:
                decision_info = ctrl.tick_and_decide(
                    time_sec=_time_sec,
                    counts=counts,
                    queues=queues,
                    emergency=emergency,
                )

            if west_source == "camera":
                decision_info.reason = f"{decision_info.reason} [west_source=camera]"
            else:
                decision_info.reason = f"{decision_info.reason} [west_source=sumo]"

            # 8) Send phase command
            effective_manual_command = _get_effective_manual_command(manual_command)
            if manual_mode == "MANUAL" and effective_manual_command and not emergency.active:
                sumo_connector.apply_manual_command(effective_manual_command, max(1, ctrl.remaining_green))
            else:
                sumo_connector.set_green_phase(ctrl.current_green, max(1, ctrl.remaining_green))

            # 9) Manual info
            from controller.state_models import ManualInfo
            manual_info = ManualInfo(
                active=(manual_mode == "MANUAL"),
                command=manual_command,
                remaining_seconds=_get_manual_remaining(current_real_time),
            )

            # 9a) Input health
            input_health = InputHealthInfo(**provider.get_health_status())

            # 10) Actual SUMO state
            actual_green_info = sumo_connector.get_actual_green_info()

            # 10.5) WEST camera info
            camera_info_dict = provider.get_camera_info()
            west_camera = WestCameraInfo(
                camera_ok=camera_info_dict["camera_ok"],
                last_frame_ts=camera_info_dict["last_frame_ts"],
                detections=[DetectionInfo(**d) for d in camera_info_dict["detections"]],
                using_fake_fallback=camera_info_dict["using_fake_fallback"],
            )

            if _time_sec % 2 == 0:
                west_total = sum(counts.west_entry.dict().values())
                logger.info(f"[STATUS_BUILD] t={_time_sec}, WEST_total={west_total}, WEST_counts={counts.west_entry.dict()}")

            # 11) Build status object
            _current_status = StatusResponse(
                time=_time_sec,
                counts=counts,
                queues=queues,
                signal=SignalState(greenRoad=ctrl.current_green, remaining=ctrl.remaining_green),
                emergency=emergency,
                decision=decision_info,
                metrics=metrics,
                prediction=_convert_predictions_to_prediction_set(predictions),
                mode=manual_mode,
                manual=manual_info,
                inputs=input_health,
                west_camera=west_camera,
                sumo_phase_index=actual_green_info["sumo_phase_index"],
                sumo_tls_state=actual_green_info["sumo_tls_state"],
                actual_green_group=actual_green_info["actual_green_group"],
                actual_green_roads=actual_green_info["actual_green_roads"],
            )

            # 12) Log metrics
            if _time_sec % controller.decision_cycle == 0:
                _log_metrics(_time_sec, metrics, _current_status.signal, predictions)

            # 13) Broadcast
            await _broadcast_update(_current_status)

            # 14) Tick
            _time_sec += 1
            await asyncio.sleep(1)

        simulation_active = False
        if sumo_connector:
            sumo_connector.disconnect()

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Error in simulation loop: {e}")
        logger.error("Simulation loop crashed", exc_info=True)
        simulation_active = False
        if sumo_connector:
            sumo_connector.disconnect()


@app.on_event("startup")
async def startup_event():
    global _accident_task
    logger.info("Starting accident detection background task")
    _accident_task = asyncio.create_task(_accident_detection_loop())

import uuid

async def _accident_detection_loop():
    global accident_state, fire_smoke_state, emergency_state
    global last_accident_trigger_time
    logger.info("[SURVEILLANCE_LOOP] Accident & Fire/Smoke dual-frequency loop started.")
    
    await asyncio.sleep(2)
    
    # Track timers independently
    last_accident_check_ts = 0.0
    last_fire_smoke_check_ts = 0.0
    
    while True:
        try:
            current_time = time.time()
            frame_bytes = None
            frame_bgr = None
            
            # 1. Determine Fire/Smoke Frequency
            current_fs_interval = FIRE_SMOKE_PASSIVE_CHECK_INTERVAL_SEC
            if accident_state["active"] or emergency_state["popupActive"]:
                current_fs_interval = FIRE_SMOKE_EMERGENCY_CHECK_INTERVAL_SEC
                
            # 2. Check Accident
            if ACCIDENT_MODEL_ENABLED and accident_detector is not None and accident_detector.is_ready():
                if current_time - last_accident_check_ts >= ACCIDENT_CHECK_INTERVAL_SEC:
                    last_accident_check_ts = current_time
                    frame_bytes = data_provider.get_raw_camera_frame_jpeg()
                    if frame_bytes:
                        frame_bgr = _decode_jpeg_to_bgr(frame_bytes)
                        if frame_bgr is not None:
                            accident_result = accident_detector.predict_frame(frame_bgr)
                            is_active = accident_result.get("active", False)
                            confidence = float(accident_result.get("confidence", 0.0))
                            
                            if is_active:
                                accident_state.update({
                                    "active": True,
                                    "confidence": confidence,
                                    "label": accident_result.get("label", "Accident"),
                                    "lastDetectedTs": current_time,
                                    "lastDetectedAt": datetime.utcnow().isoformat() + "Z",
                                })
                                
                                # Trigger global emergency state
                                if not emergency_state["popupActive"] and current_time - last_accident_trigger_time > ACCIDENT_TRIGGER_COOLDOWN_SEC:
                                    emergency_state["id"] = str(uuid.uuid4())
                                    emergency_state["popupActive"] = True
                                    emergency_state["requiresAck"] = EMERGENCY_POPUP_REQUIRE_ACK
                                    emergency_state["acknowledged"] = False
                                    
                                    logger.warning(f"[EMERGENCY] New accident emergency triggered: conf={confidence:.2f}")
                                    try:
                                        await _trigger_accident_workflow(confidence=confidence, area=ACCIDENT_ROAD_ID)
                                    except Exception as e:
                                        logger.error(f"Failed to trigger accident workflow: {e}")
                                    last_accident_trigger_time = current_time
                            else:
                                if accident_state["active"] and current_time - accident_state.get("lastDetectedTs", 0) > 10:
                                    accident_state["active"] = False
                                    accident_state["confidence"] = 0.0
                                    accident_state["label"] = "Non_Accident"
                                    logger.info("[ACCIDENT] Accident cleared from active state.")

            # 3. Check Fire/Smoke
            if FIRE_SMOKE_MODEL_ENABLED and fire_smoke_detector is not None and fire_smoke_detector.is_ready():
                if current_time - last_fire_smoke_check_ts >= current_fs_interval:
                    last_fire_smoke_check_ts = current_time
                    
                    if frame_bgr is None:
                        frame_bytes = data_provider.get_raw_camera_frame_jpeg()
                        if frame_bytes:
                            frame_bgr = _decode_jpeg_to_bgr(frame_bytes)
                            
                    if frame_bgr is not None:
                        fs_result = fire_smoke_detector.predict_frame(frame_bgr)
                        fire_smoke_state["checking"] = True
                        fire_smoke_state["lastCheckedAt"] = datetime.utcnow().isoformat() + "Z"
                        
                        if fs_result["fire_detected"] or fs_result["smoke_detected"]:
                            fire_smoke_state.update({
                                "fireDetected": fs_result["fire_detected"],
                                "smokeDetected": fs_result["smoke_detected"],
                                "fireConfidence": fs_result["fire_confidence"],
                                "smokeConfidence": fs_result["smoke_confidence"],
                                "boxes": fs_result["boxes"],
                                "lastDetectedTs": current_time,
                                "lastDetectedAt": datetime.utcnow().isoformat() + "Z",
                            })
                        else:
                            # 10s latch
                            if current_time - fire_smoke_state["lastDetectedTs"] > FIRE_SMOKE_ALERT_LATCH_SEC:
                                fire_smoke_state.update({
                                    "fireDetected": False,
                                    "smokeDetected": False,
                                    "fireConfidence": 0.0,
                                    "smokeConfidence": 0.0,
                                    "boxes": []
                                })
                                
            # 4. Synthesize Global Emergency State
            emergency_state["accidentActive"] = accident_state["active"]
            emergency_state["accidentConfidence"] = accident_state["confidence"]
            emergency_state["fireSmokeChecked"] = fire_smoke_state["checking"]
            emergency_state["fireDetected"] = fire_smoke_state["fireDetected"]
            emergency_state["smokeDetected"] = fire_smoke_state["smokeDetected"]
            emergency_state["fireConfidence"] = fire_smoke_state["fireConfidence"]
            emergency_state["smokeConfidence"] = fire_smoke_state["smokeConfidence"]
            
            if emergency_state["popupActive"]:
                if emergency_state["fireDetected"] and emergency_state["smokeDetected"]:
                    emergency_state["emergencyLevel"] = "CRITICAL_EMERGENCY"
                    emergency_state["message"] = "Accident with Fire and Smoke Detected"
                elif emergency_state["fireDetected"]:
                    emergency_state["emergencyLevel"] = "CRITICAL_EMERGENCY"
                    emergency_state["message"] = "Accident with Fire Detected"
                elif emergency_state["smokeDetected"]:
                    emergency_state["emergencyLevel"] = "HIGH_RISK_EMERGENCY"
                    emergency_state["message"] = "Accident with Smoke Detected"
                else:
                    emergency_state["emergencyLevel"] = "ACCIDENT_CONFIRMED"
                    emergency_state["message"] = "Accident Detected"
            else:
                emergency_state["emergencyLevel"] = "NORMAL"
                emergency_state["message"] = "No emergency detected."
                
        except Exception as e:
            logger.error(f"[SURVEILLANCE_LOOP] Error: {e}", exc_info=True)
            
        # The loop spins fast enough to accommodate the highest frequency
        await asyncio.sleep(0.05)

@app.get("/api/accident/status")
async def get_accident_status():
    return accident_state

@app.get("/api/fire-smoke/status")
async def get_fire_smoke_status():
    return fire_smoke_state

@app.get("/api/emergency/status")
async def get_emergency_status():
    return emergency_state

@app.post("/api/emergency/ack")
async def ack_emergency():
    emergency_state["popupActive"] = False
    emergency_state["acknowledged"] = True
    return {"status": "success", "message": "Emergency acknowledged and popup closed."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)