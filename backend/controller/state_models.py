from enum import Enum
from typing import Dict, Optional, List
from pydantic import BaseModel

class Road(str, Enum):
    west_entry = "west_entry"
    j1_north_entry = "j1_north_entry"
    j8_north_entry = "j8_north_entry"
    j8_east_entry = "j8_east_entry"
    j8_south_entry = "j8_south_entry"

class VehicleType(str, Enum):
    car = "car"
    bike = "bike"
    bus = "bus"
    truck = "truck"
    lorry = "lorry"
    auto = "auto"

class RoadVehicleCounts(BaseModel):
    car: int = 0
    bike: int = 0
    bus: int = 0
    truck: int = 0
    lorry: int = 0
    auto: int = 0

class TrafficCounts(BaseModel):
    west_entry: RoadVehicleCounts
    j1_north_entry: RoadVehicleCounts
    j8_north_entry: RoadVehicleCounts
    j8_east_entry: RoadVehicleCounts
    j8_south_entry: RoadVehicleCounts

class SignalState(BaseModel):
    greenRoad: Road
    remaining: int

class EmergencyInfo(BaseModel):
    active: bool
    road: Optional[Road]

class DecisionInfo(BaseModel):
    method: str
    reason: str

class RoadMetrics(BaseModel):
    """Per-road metrics for traffic analysis"""
    waiting_count: int = 0
    avg_wait_time: float = 0.0
    cleared_last_interval: int = 0
    arrival_rate_vpm: float = 0.0
    departure_rate_vpm: float = 0.0
    time_since_last_green: float = 0.0
    congestion_percent: float = 0.0
    eta_clear_seconds: float = 0.0

class RoadMetricsSet(BaseModel):
    """Metrics for all entry roads"""
    west_entry: RoadMetrics = RoadMetrics()
    j1_north_entry: RoadMetrics = RoadMetrics()
    j8_north_entry: RoadMetrics = RoadMetrics()
    j8_east_entry: RoadMetrics = RoadMetrics()
    j8_south_entry: RoadMetrics = RoadMetrics()

class PredictionMetrics(BaseModel):
    """Per-road short-term traffic predictions"""
    queue_trend: str = "stable"  # "increasing", "stable", "decreasing"
    arrivals_10s: float = 0.0    # Predicted arrivals in next 10 seconds
    arrivals_30s: float = 0.0    # Predicted arrivals in next 30 seconds
    heavy_traffic_probability: float = 0.0  # 0-100%
    congestion_level: str = "LOW"  # "LOW", "MEDIUM", "HIGH"
    predicted_eta_clear_seconds: float = 0.0  # Estimated time to clear queue

class PredictionSet(BaseModel):
    """Predictions for all entry roads"""
    west_entry: PredictionMetrics = PredictionMetrics()
    j1_north_entry: PredictionMetrics = PredictionMetrics()
    j8_north_entry: PredictionMetrics = PredictionMetrics()
    j8_east_entry: PredictionMetrics = PredictionMetrics()
    j8_south_entry: PredictionMetrics = PredictionMetrics()

class MemoryRecord(BaseModel):
    """Record of a state-action-reward experience for learning."""
    time: int
    state_queues: Dict[Road, int]
    action_road: Road
    action_duration: int
    reward: float
    reason: str

class ManualCommand(BaseModel):
    """Manual override command details"""
    command: str  # "NS_GREEN" | "EW_GREEN" | "ALL_RED"
    duration: int
    start_time: float

class ManualInfo(BaseModel):
    """Manual control status"""
    active: bool
    command: Optional[str] = None
    remaining_seconds: int = 0

class InputHealthInfo(BaseModel):
    """Health status of input data sources"""
    west_source: str = "fake"  # "camera" or "fake"
    camera_ok: bool = False
    last_camera_ts: float = 0.0
    camera_error_count: int = 0
    west_source_mode: Optional[str] = None  # "webcam" or "video" (Task 3)
    west_video_path: Optional[str] = None  # Video file path (Task 3)

class DetectionInfo(BaseModel):
    """Single detection metadata"""
    cls_raw: str
    cls_mapped: str
    conf: float
    x1: int
    y1: int
    x2: int
    y2: int

class WestCameraInfo(BaseModel):
    """West camera detailed information"""
    camera_ok: bool = False
    last_frame_ts: float = 0.0
    detections: List[DetectionInfo] = []
    using_fake_fallback: bool = True

class StatusResponse(BaseModel):
    time: int
    counts: TrafficCounts
    queues: Dict[Road, int]
    signal: SignalState
    emergency: EmergencyInfo
    decision: DecisionInfo
    metrics: RoadMetricsSet = RoadMetricsSet()
    prediction: PredictionSet = PredictionSet()
    mode: str = "AUTO"
    manual: ManualInfo = ManualInfo(active=False)
    inputs: InputHealthInfo = InputHealthInfo()
    west_camera: WestCameraInfo = WestCameraInfo()
    # SUMO actual state
    sumo_phase_index: int = -1
    sumo_tls_state: str = ""
    actual_green_group: str = "UNKNOWN"
    actual_green_roads: List[str] = []
