from enum import Enum
from typing import Dict, Optional
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

class StatusResponse(BaseModel):
    time: int
    counts: TrafficCounts
    queues: Dict[Road, int]
    signal: SignalState
    emergency: EmergencyInfo
    decision: DecisionInfo

class MemoryRecord(BaseModel):
    time: int
    state_queues: Dict[Road, int]
    action_road: Road
    action_duration: int
    reward: float
    reason: str
