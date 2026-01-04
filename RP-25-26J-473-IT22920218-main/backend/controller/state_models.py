from enum import Enum
from typing import Dict, Optional, List
from pydantic import BaseModel

class Road(str, Enum):
    north = "north"
    east = "east"
    south = "south"
    west = "west"

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
    north: RoadVehicleCounts
    east: RoadVehicleCounts
    south: RoadVehicleCounts
    west: RoadVehicleCounts

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
    """Metrics for all four roads"""
    north: RoadMetrics = RoadMetrics()
    east: RoadMetrics = RoadMetrics()
    south: RoadMetrics = RoadMetrics()
    west: RoadMetrics = RoadMetrics()

class PredictionMetrics(BaseModel):
    """Per-road short-term traffic predictions"""
    queue_trend: str = "stable"  # "increasing", "stable", "decreasing"
    arrivals_10s: float = 0.0    # Predicted arrivals in next 10 seconds
    arrivals_30s: float = 0.0    # Predicted arrivals in next 30 seconds
    heavy_traffic_probability: float = 0.0  # 0-100%
    congestion_level: str = "LOW"  # "LOW", "MEDIUM", "HIGH"
    predicted_eta_clear_seconds: float = 0.0  # Estimated time to clear queue

class PredictionSet(BaseModel):
    """Predictions for all four roads"""
    north: PredictionMetrics = PredictionMetrics()
    east: PredictionMetrics = PredictionMetrics()
    south: PredictionMetrics = PredictionMetrics()
    west: PredictionMetrics = PredictionMetrics()

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
    # SUMO actual state
    sumo_phase_index: int = -1
    sumo_tls_state: str = ""
    actual_green_group: str = "UNKNOWN"
    actual_green_roads: List[str] = []
